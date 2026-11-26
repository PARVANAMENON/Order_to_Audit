"""GST engine, invoice numbering, order/invoice/dispatch posting services."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import log_action
from apps.inventory.models import SourceType, StockLedger
from apps.inventory.services import balance, get_wac
from apps.masters.models import Customer, Item
from apps.masters.services import convert_quantity
from apps.sales.models import (
    CreditNote,
    Dispatch,
    DispatchStatus,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Order,
    OrderLine,
    OrderStatus,
)

MONEY = Decimal("0.01")
HALF_GST_RATE = Decimal("2.5")  # 5% GST split as 2.5+2.5 for intra-state
STATE_TN = "Tamil Nadu"


def _is_intra_state(customer: Customer) -> bool:
    return customer.state.strip().lower() == STATE_TN.lower()


def _compute_gst(taxable: Decimal, gst_rate: Decimal, intra: bool) -> dict[str, Decimal]:
    tax = (taxable * gst_rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
    if intra:
        half = (tax / 2).quantize(MONEY, rounding=ROUND_HALF_UP)
        return {"cgst": half, "sgst": tax - half, "igst": Decimal("0.00")}
    return {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": tax}


def _next_fy_number() -> str:
    """Generate next gapless FY invoice number inside a locked transaction."""
    from django.db import connection

    year = timezone.now().year
    # Financial year: April–March
    if timezone.now().month >= 4:
        fy = f"{year}-{str(year + 1)[-2:]}"
    else:
        fy = f"{year - 1}-{str(year)[-2:]}"

    with connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sales_invoice WHERE fy_number LIKE %s", [f"{fy}/%"]
        )
        seq = cur.fetchone()[0] + 1
    return f"{fy}/{seq:04d}"


def _next_cn_number() -> str:
    """Generate next gapless credit-note number."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sales_creditnote")
        seq = cur.fetchone()[0] + 1
    return f"CN-{seq:04d}"


@transaction.atomic
def submit_order(
    *,
    customer: Customer,
    salesman: User,
    lines: list[dict],
    notes: str = "",
    idempotency_key: uuid.UUID | None = None,
) -> Order:
    """Create or return an existing order using the idempotency key (safe for offline retry)."""
    key = idempotency_key or uuid.uuid4()
    existing = Order.objects.filter(idempotency_key=key).first()
    if existing:
        return existing

    order = Order.objects.create(
        customer=customer,
        salesman=salesman,
        status=OrderStatus.SUBMITTED,
        idempotency_key=key,
        notes=notes,
    )
    for line in lines:
        item = line["item"]
        OrderLine.objects.create(
            order=order,
            item=item,
            qty=Decimal(str(line["qty"])),
            unit=line["unit"],
            unit_price=Decimal(str(line["unit_price"])),
        )
    log_action(
        user=salesman,
        model_name="Order",
        object_id=order.id,
        action="submit_order",
        after={"status": order.status, "customer": customer.name, "lines": len(lines)},
        notes=f"ORD-{order.id}",
    )
    return order


@transaction.atomic
def approve_order(
    order: Order, *, user: User, line_adjustments: dict | None = None
) -> tuple[Order, list[dict]]:
    """Approve an order, optionally adjusting quantities, and check stock coverage."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status != OrderStatus.SUBMITTED:
        raise ValidationError(f"Cannot approve order in status '{locked.status}'.")

    if line_adjustments:
        for line in locked.lines.all():
            if line.id in line_adjustments:
                adj_qty = Decimal(str(line_adjustments[line.id]))
                if adj_qty < 0:
                    raise ValidationError("Adjusted qty cannot be negative.")
                line.approved_qty = adj_qty
                line.save(update_fields=["approved_qty"])

    # Stock coverage check for FG items
    shortages = []
    for line in locked.lines.select_related("item", "item__base_unit", "unit").all():
        if line.item.item_type != "finished":
            continue
        req_base = convert_quantity(line.effective_qty, line.unit, line.item.base_unit)
        avail = balance(line.item)
        if avail < req_base:
            shortages.append(
                {
                    "sku": line.item.sku,
                    "required": req_base,
                    "available": avail,
                    "shortage": req_base - avail,
                }
            )

    locked.status = OrderStatus.APPROVED
    locked.approved_by = user
    locked.approved_at = timezone.now()
    locked.save(update_fields=["status", "approved_by", "approved_at"])
    log_action(
        user=user,
        model_name="Order",
        object_id=locked.id,
        action="approve_order",
        before={"status": OrderStatus.SUBMITTED},
        after={"status": locked.status, "shortages": shortages},
        notes=f"ORD-{locked.id}",
    )
    return locked, shortages


@transaction.atomic
def reject_order(order: Order, *, user: User, reason: str) -> Order:
    """Reject a submitted order with a mandatory reason."""
    if not reason.strip():
        raise ValidationError("Rejection reason is mandatory.")
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status != OrderStatus.SUBMITTED:
        raise ValidationError(f"Cannot reject order in status '{locked.status}'.")
    locked.status = OrderStatus.REJECTED
    locked.rejection_reason = reason.strip()
    locked.approved_by = user
    locked.approved_at = timezone.now()
    locked.save(update_fields=["status", "rejection_reason", "approved_by", "approved_at"])
    log_action(
        user=user,
        model_name="Order",
        object_id=locked.id,
        action="reject_order",
        before={"status": OrderStatus.SUBMITTED},
        after={"status": locked.status, "rejection_reason": locked.rejection_reason},
        notes=f"ORD-{locked.id}",
    )
    return locked


@transaction.atomic
def post_invoice(order: Order, *, user: User) -> Invoice:
    """Create a GST invoice from an approved order inside one atomic transaction."""
    locked = Order.objects.select_for_update().get(pk=order.pk)

    # Idempotency: return the existing invoice before re-checking the order status.
    if hasattr(locked, "invoice"):
        return locked.invoice

    if locked.status != OrderStatus.APPROVED:
        raise ValidationError(f"Order must be approved before invoicing (status: {locked.status}).")

    intra = _is_intra_state(locked.customer)
    place_of_supply = locked.customer.state

    total_taxable = Decimal("0.00")
    total_cgst = Decimal("0.00")
    total_sgst = Decimal("0.00")
    total_igst = Decimal("0.00")

    fy_number = _next_fy_number()
    invoice = Invoice.objects.create(
        order=locked,
        fy_number=fy_number,
        customer=locked.customer,
        invoice_date=timezone.localdate(),
        place_of_supply=place_of_supply,
        created_by=user,
    )

    for line in locked.lines.select_related("item", "unit").all():
        taxable = line.line_taxable
        gst = _compute_gst(taxable, line.item.gst_rate, intra)
        cgst = gst["cgst"]
        sgst = gst["sgst"]
        igst = gst["igst"]
        line_total = taxable + cgst + sgst + igst

        InvoiceLine.objects.create(
            invoice=invoice,
            item=line.item,
            hsn=line.item.hsn,
            qty=line.effective_qty,
            unit=line.unit,
            unit_price=line.unit_price,
            taxable_value=taxable,
            gst_rate=line.item.gst_rate,
            cgst=cgst,
            sgst=sgst,
            igst=igst,
            line_total=line_total,
        )
        total_taxable += taxable
        total_cgst += cgst
        total_sgst += sgst
        total_igst += igst

    invoice.taxable_value = total_taxable.quantize(MONEY, rounding=ROUND_HALF_UP)
    invoice.cgst = total_cgst.quantize(MONEY, rounding=ROUND_HALF_UP)
    invoice.sgst = total_sgst.quantize(MONEY, rounding=ROUND_HALF_UP)
    invoice.igst = total_igst.quantize(MONEY, rounding=ROUND_HALF_UP)
    invoice.total_amount = (total_taxable + total_cgst + total_sgst + total_igst).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )
    invoice.save(
        update_fields=["taxable_value", "cgst", "sgst", "igst", "total_amount"]
    )

    locked.status = OrderStatus.INVOICED
    locked.save(update_fields=["status"])
    log_action(
        user=user,
        model_name="Invoice",
        object_id=invoice.id,
        action="post_invoice",
        after={
            "fy_number": invoice.fy_number,
            "taxable_value": str(invoice.taxable_value),
            "total_amount": str(invoice.total_amount),
            "place_of_supply": invoice.place_of_supply,
        },
        notes=f"ORD-{locked.id}",
    )
    return invoice


@transaction.atomic
def post_dispatch(invoice: Invoice, *, user: User) -> Dispatch:
    """Deduct FG stock and create a Dispatch document inside one atomic transaction."""
    locked_inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked_inv.status != InvoiceStatus.ACTIVE:
        raise ValidationError("Cannot dispatch against a cancelled invoice.")

    existing = locked_inv.dispatches.exclude(status=DispatchStatus.PENDING).first()
    if existing:
        return existing

    dispatch = Dispatch.objects.create(
        invoice=locked_inv,
        dispatch_date=timezone.localdate(),
        dispatched_by=user,
        dispatched_at=timezone.now(),
        status=DispatchStatus.DISPATCHED,
    )

    movement_dt = timezone.now()
    shortages = []

    for line in locked_inv.lines.select_related(
        "item", "item__base_unit", "unit"
    ).all():
        if line.item.item_type != "finished":
            continue
        base_qty = convert_quantity(line.qty, line.unit, line.item.base_unit)
        item = Item.objects.select_for_update().get(pk=line.item_id)
        avail = balance(item)
        if avail < base_qty:
            shortages.append({"sku": item.sku, "required": base_qty, "available": avail})
            continue
        wac = get_wac(item)
        StockLedger.objects.create(
            item=item,
            date=movement_dt,
            qty=-base_qty,
            unit_rate=wac,
            source_type=SourceType.DISPATCH,
            source_id=dispatch.id,
            source_ref=locked_inv.fy_number,
            user=user,
            notes=f"Dispatched for {locked_inv.fy_number}",
        )

    if shortages:
        dispatch.status = DispatchStatus.PARTIAL
        dispatch.notes = "Partial: " + "; ".join(
            f"{s['sku']} short {s['required'] - s['available']}" for s in shortages
        )
        dispatch.save(update_fields=["status", "notes"])

    log_action(
        user=user,
        model_name="Dispatch",
        object_id=dispatch.id,
        action="post_dispatch",
        after={"invoice": locked_inv.fy_number, "status": dispatch.status},
        notes=f"DISP-{dispatch.id}",
    )
    return dispatch


@transaction.atomic
def post_credit_note(
    invoice: Invoice, *, user: User, reason: str, reverses_stock: bool = False
) -> CreditNote:
    """Cancel an invoice with a credit note, reversing revenue, tax, and optionally stock."""
    if not reason.strip():
        raise ValidationError("Credit note reason is mandatory.")
    locked_inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked_inv.status == InvoiceStatus.CANCELLED:
        raise ValidationError("Invoice is already cancelled.")

    cn_number = _next_cn_number()
    cn = CreditNote.objects.create(
        invoice=locked_inv,
        cn_number=cn_number,
        reason=reason.strip(),
        reverses_stock=reverses_stock,
        taxable_value=locked_inv.taxable_value,
        cgst=locked_inv.cgst,
        sgst=locked_inv.sgst,
        igst=locked_inv.igst,
        total_amount=locked_inv.total_amount,
        created_by=user,
    )

    if reverses_stock:
        movement_dt = timezone.now()
        for line in locked_inv.lines.select_related("item", "item__base_unit", "unit").all():
            if line.item.item_type != "finished":
                continue
            base_qty = convert_quantity(line.qty, line.unit, line.item.base_unit)
            wac = get_wac(line.item)
            StockLedger.objects.create(
                item=line.item,
                date=movement_dt,
                qty=base_qty,
                unit_rate=wac,
                source_type=SourceType.CREDIT_NOTE,
                source_id=cn.id,
                source_ref=cn_number,
                user=user,
                notes=f"Stock return: credit note {cn_number}",
            )

    locked_inv.status = InvoiceStatus.CANCELLED
    locked_inv.save(update_fields=["status"])
    log_action(
        user=user,
        model_name="CreditNote",
        object_id=cn.id,
        action="post_credit_note",
        before={"invoice_status": InvoiceStatus.ACTIVE},
        after={
            "invoice_status": locked_inv.status,
            "cn_number": cn.cn_number,
            "total_amount": str(cn.total_amount),
            "reverses_stock": cn.reverses_stock,
        },
        notes=f"{cn.cn_number} for {locked_inv.fy_number}",
    )
    return cn

