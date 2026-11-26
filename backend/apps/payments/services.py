"""Payment posting and outstanding/ageing computation services."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import log_action
from apps.masters.models import Customer
from apps.payments.models import Payment, PaymentAllocation
from apps.sales.models import Invoice, InvoiceStatus

MONEY = Decimal("0.01")


def outstanding_for_invoice(invoice: Invoice) -> Decimal:
    """Return unpaid amount on a single invoice."""
    paid = invoice.payment_allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    return max(invoice.total_amount - Decimal(str(paid)), Decimal("0.00"))


def customer_outstanding(customer: Customer) -> Decimal:
    """Return total outstanding across all active invoices for a customer."""
    invoices = Invoice.objects.filter(customer=customer, status=InvoiceStatus.ACTIVE)
    total = Decimal("0.00")
    for inv in invoices:
        total += outstanding_for_invoice(inv)
    return total.quantize(MONEY, rounding=ROUND_HALF_UP)


def ageing_buckets(customer: Customer, as_of: date | None = None) -> dict[str, Decimal]:
    """Return outstanding split into 0-30, 31-60, 61-90, 90+ day buckets."""
    today = as_of or timezone.localdate()
    buckets = {
        "0_30": Decimal("0.00"),
        "31_60": Decimal("0.00"),
        "61_90": Decimal("0.00"),
        "90_plus": Decimal("0.00"),
    }
    for inv in Invoice.objects.filter(customer=customer, status=InvoiceStatus.ACTIVE):
        outstanding = outstanding_for_invoice(inv)
        if outstanding <= 0:
            continue
        age = (today - inv.invoice_date).days
        if age <= 30:
            buckets["0_30"] += outstanding
        elif age <= 60:
            buckets["31_60"] += outstanding
        elif age <= 90:
            buckets["61_90"] += outstanding
        else:
            buckets["90_plus"] += outstanding
    return {k: v.quantize(MONEY, rounding=ROUND_HALF_UP) for k, v in buckets.items()}


@transaction.atomic
def post_payment(
    *,
    customer: Customer,
    amount: Decimal | str,
    payment_date: date | None = None,
    reference: str = "",
    notes: str = "",
    allocations: list[dict] | None = None,
    user: User,
) -> Payment:
    """Record a customer payment and allocate to invoices atomically.

    `allocations` is a list of {"invoice_id": int, "amount": Decimal}.
    If omitted, automatically allocates to oldest outstanding invoices (FIFO by date).
    """
    dec_amount = Decimal(str(amount)).quantize(MONEY, rounding=ROUND_HALF_UP)
    if dec_amount <= 0:
        raise ValidationError("Payment amount must be positive.")

    pay = Payment.objects.create(
        customer=customer,
        amount=dec_amount,
        payment_date=payment_date or timezone.localdate(),
        reference=reference.strip(),
        notes=notes.strip(),
        received_by=user,
    )

    remaining = dec_amount
    if allocations:
        for alloc in allocations:
            inv = Invoice.objects.get(pk=alloc["invoice_id"])
            if inv.customer_id != customer.id:
                raise ValidationError(
                    f"Invoice {inv.fy_number} does not belong to {customer.name}."
                )
            if inv.status != InvoiceStatus.ACTIVE:
                raise ValidationError(f"Cannot allocate to cancelled invoice {inv.fy_number}.")
            alloc_amt = Decimal(str(alloc["amount"])).quantize(MONEY, rounding=ROUND_HALF_UP)
            outstanding = outstanding_for_invoice(inv)
            if alloc_amt > outstanding + Decimal("0.01"):
                raise ValidationError(
                    f"Allocation {alloc_amt} exceeds outstanding {outstanding} for {inv.fy_number}."
                )
            PaymentAllocation.objects.create(payment=pay, invoice=inv, amount=alloc_amt)
            remaining -= alloc_amt
    else:
        # Auto-FIFO allocation
        for inv in Invoice.objects.filter(
            customer=customer, status=InvoiceStatus.ACTIVE
        ).order_by("invoice_date", "id"):
            if remaining <= 0:
                break
            outstanding = outstanding_for_invoice(inv)
            if outstanding <= 0:
                continue
            alloc_amt = min(remaining, outstanding).quantize(MONEY, rounding=ROUND_HALF_UP)
            PaymentAllocation.objects.create(payment=pay, invoice=inv, amount=alloc_amt)
            remaining -= alloc_amt

    log_action(
        user=user,
        model_name="Payment",
        object_id=pay.id,
        action="post_payment",
        after={
            "customer": customer.name,
            "amount": str(dec_amount),
            "allocated": str((dec_amount - remaining).quantize(MONEY)),
            "unallocated": str(remaining.quantize(MONEY)),
        },
        notes=f"PAY-{pay.id}",
    )
    return pay
