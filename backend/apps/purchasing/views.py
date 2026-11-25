"""Views for purchasing entry, listing, detail, and posting."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.inventory.models import SourceType, StockLedger
from apps.masters.models import Item, ItemType, Supplier, Unit
from apps.masters.services import UnitConversionError, _to_decimal
from apps.purchasing.models import Purchase, PurchaseLine
from apps.purchasing.services import post_purchase

VIEW_ROLES = (Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)
WRITE_ROLES = (Role.ADMIN, Role.PRODUCTION)


@role_required(*VIEW_ROLES)
def purchase_list_view(request: HttpRequest) -> HttpResponse:
    """List supplier purchases."""
    purchases = Purchase.objects.select_related("supplier", "created_by", "posted_by").all()
    return render(request, "purchasing/list.html", {"purchases": purchases})


@role_required(*WRITE_ROLES)
def purchase_create_view(request: HttpRequest) -> HttpResponse:
    """Create a purchase receipt (and optionally post it immediately)."""
    suppliers = Supplier.objects.filter(is_active=True)
    items = Item.objects.filter(
        is_active=True, item_type__in=[ItemType.RAW, ItemType.PACK]
    ).select_related("base_unit", "display_unit")
    units = Unit.objects.all()

    if request.method == "POST":
        supplier = get_object_or_404(Supplier, pk=request.POST.get("supplier_id"))
        invoice_number = request.POST.get("invoice_number", "").strip()
        date_str = request.POST.get("date", "").strip()
        notes = request.POST.get("notes", "").strip()
        post_now = request.POST.get("action") == "save_and_post"

        item_ids = request.POST.getlist("item_id")
        qtys = request.POST.getlist("qty")
        unit_ids = request.POST.getlist("unit_id")
        rates = request.POST.getlist("unit_rate")
        batches = request.POST.getlist("batch")

        try:
            if not invoice_number:
                raise ValidationError("Supplier invoice number is required.")
            parsed_date = (
                timezone.datetime.fromisoformat(date_str).date()
                if date_str
                else timezone.localdate()
            )
            with transaction.atomic():
                purchase = Purchase.objects.create(
                    supplier=supplier,
                    invoice_number=invoice_number,
                    date=parsed_date,
                    notes=notes,
                    created_by=request.user,
                )
                line_count = 0
                for idx, item_id in enumerate(item_ids):
                    if not item_id:
                        continue
                    qty_val = _to_decimal(qtys[idx])
                    rate_val = _to_decimal(rates[idx])
                    if qty_val <= Decimal("0"):
                        raise ValidationError("Purchase line quantity must be positive.")
                    line_item = get_object_or_404(Item, pk=item_id)
                    line_unit = get_object_or_404(Unit, pk=unit_ids[idx])
                    batch_val = batches[idx].strip() if idx < len(batches) else ""
                    PurchaseLine.objects.create(
                        purchase=purchase,
                        item=line_item,
                        qty=qty_val,
                        unit=line_unit,
                        unit_rate=rate_val,
                        batch=batch_val or None,
                    )
                    line_count += 1
                if line_count == 0:
                    raise ValidationError("Add at least one purchase line.")
                if post_now:
                    post_purchase(purchase, request.user)
                    messages.success(request, f"Purchase PUR-{purchase.id} posted to ledger.")
                else:
                    messages.success(request, f"Draft purchase PUR-{purchase.id} saved.")
            return redirect("purchasing:detail", pk=purchase.id)
        except (
            ValidationError,
            UnitConversionError,
            ValueError,
            TypeError,
            ArithmeticError,
        ) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "purchasing/create.html",
        {
            "suppliers": suppliers,
            "items": items,
            "units": units,
            "today": timezone.localdate().isoformat(),
        },
    )


@role_required(*VIEW_ROLES)
def purchase_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View a purchase document and its linked StockLedger rows."""
    purchase = get_object_or_404(
        Purchase.objects.select_related("supplier", "created_by", "posted_by"), pk=pk
    )
    lines = purchase.lines.select_related("item", "unit", "item__base_unit").all()
    ledger_rows = StockLedger.objects.filter(
        source_type=SourceType.PURCHASE, source_id=purchase.id
    ).select_related("item", "user")
    return render(
        request,
        "purchasing/detail.html",
        {"purchase": purchase, "lines": lines, "ledger_rows": ledger_rows},
    )


@role_required(*WRITE_ROLES)
def purchase_post_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Post a draft purchase to StockLedger."""
    if request.method != "POST":
        return redirect("purchasing:detail", pk=pk)
    purchase = get_object_or_404(Purchase, pk=pk)
    try:
        post_purchase(purchase, request.user)
        messages.success(request, f"Purchase PUR-{purchase.id} posted to StockLedger.")
    except (ValidationError, UnitConversionError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("purchasing:detail", pk=purchase.id)
