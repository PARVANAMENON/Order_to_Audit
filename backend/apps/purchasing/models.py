"""Purchase and PurchaseLine models."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import Item, Supplier, Unit


class PurchaseStatus(models.TextChoices):
    """Lifecycle states of a purchase document."""

    DRAFT = "draft", "Draft"
    POSTED = "posted", "Posted"


class Purchase(models.Model):
    """Supplier purchase receipt header."""

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchases",
    )
    invoice_number = models.CharField(max_length=64)
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=16,
        choices=PurchaseStatus.choices,
        default=PurchaseStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_purchases",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="posted_purchases",
        null=True,
        blank=True,
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    @property
    def total_amount(self) -> Decimal:
        total = sum((line.line_total for line in self.lines.all()), Decimal("0.00"))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __str__(self) -> str:
        return f"PUR-{self.pk} ({self.invoice_number})"


class PurchaseLine(models.Model):
    """Line item on a supplier purchase receipt."""

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="purchase_lines",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    unit_rate = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        help_text="Rate per transactional unit on this purchase line.",
    )
    batch = models.CharField(max_length=64, null=True, blank=True)
    expiry = models.DateField(null=True, blank=True)

    @property
    def line_total(self) -> Decimal:
        return (self.qty * self.unit_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __str__(self) -> str:
        return f"{self.item.sku}: {self.qty} {self.unit.code} @ {self.unit_rate}"
