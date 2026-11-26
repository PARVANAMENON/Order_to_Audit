"""Order, Invoice, InvoiceLine, and Dispatch models for the sales cycle."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import Customer, Item, Unit

STATE_TN = "Tamil Nadu"


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    INVOICED = "invoiced", "Invoiced"


class Order(models.Model):
    """Sales order placed by a salesman (mobile or desktop)."""

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    salesman = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales_orders"
    )
    status = models.CharField(max_length=16, choices=OrderStatus.choices, default=OrderStatus.DRAFT)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    order_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_orders",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-order_date", "-id"]

    def __str__(self) -> str:
        return f"ORD-{self.id} {self.customer.name}"


class OrderLine(models.Model):
    """Line item on a sales order."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    # Admin may edit qty on approval
    approved_qty = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)

    @property
    def effective_qty(self) -> Decimal:
        return self.approved_qty if self.approved_qty is not None else self.qty

    @property
    def line_taxable(self) -> Decimal:
        return (self.effective_qty * self.unit_price).quantize(Decimal("0.01"))

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.item.sku}: {self.effective_qty} x {self.unit_price}"


class InvoiceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CANCELLED = "cancelled", "Cancelled"


class Invoice(models.Model):
    """GST tax invoice linked to one approved order."""

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="invoice")
    fy_number = models.CharField(max_length=20, unique=True)  # e.g. 2026-27/0001
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    invoice_date = models.DateField(default=timezone.localdate)
    place_of_supply = models.CharField(max_length=64)
    # Totals
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        max_length=16, choices=InvoiceStatus.choices, default=InvoiceStatus.ACTIVE
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_invoices"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]

    def __str__(self) -> str:
        return self.fy_number


class InvoiceLine(models.Model):
    """Detail line on a GST invoice."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    hsn = models.CharField(max_length=16, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["id"]


class DispatchStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DISPATCHED = "dispatched", "Dispatched"
    PARTIAL = "partial", "Partial"


class Dispatch(models.Model):
    """Dispatch document that posts negative StockLedger rows for FG items."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="dispatches")
    dispatch_date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=16, choices=DispatchStatus.choices, default=DispatchStatus.PENDING
    )
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dispatches"
    )
    dispatched_at = models.DateTimeField(null=True, blank=True)
    vehicle_number = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-dispatch_date", "-id"]

    def __str__(self) -> str:
        return f"DISP-{self.id} for {self.invoice.fy_number}"


class CreditNote(models.Model):
    """Credit note reversing a posted invoice's revenue, tax, and optionally stock."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    cn_number = models.CharField(max_length=20, unique=True)
    cn_date = models.DateField(default=timezone.localdate)
    reason = models.TextField()
    reverses_stock = models.BooleanField(default=False)
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credit_notes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cn_date", "-id"]

    def __str__(self) -> str:
        return self.cn_number
