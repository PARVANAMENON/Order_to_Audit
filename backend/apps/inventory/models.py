"""Stock ledger and manual adjustment models."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import Item, Unit


class SourceType(models.TextChoices):
    """Document types that post movements into the StockLedger."""

    OPENING = "opening", "Opening Balance"
    PURCHASE = "purchase", "Purchase Receipt"
    PRODUCTION_ISSUE = "production_issue", "Production Issue"
    PRODUCTION_RECEIPT = "production_receipt", "Production Output"
    PRODUCTION_REVERSAL = "production_reversal", "Production Reversal"
    ADJUSTMENT = "adjustment", "Manual Adjustment"
    DISPATCH = "dispatch", "Dispatch"
    CREDIT_NOTE = "credit_note", "Credit Note"


class StockLedger(models.Model):
    """Append-only stock movement ledger. Balance = SUM(qty) per item."""

    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    date = models.DateTimeField(default=timezone.now)
    qty = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Signed quantity in item's base unit.",
    )
    unit_rate = models.DecimalField(
        max_digits=14,
        decimal_places=6,
        help_text="Cost per base unit at movement time.",
    )
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    source_id = models.PositiveBigIntegerField()
    source_ref = models.CharField(max_length=64, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    batch = models.CharField(max_length=64, null=True, blank=True)
    expiry = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["item", "date"]),
            models.Index(fields=["source_type", "source_id"]),
        ]

    @property
    def source_url(self) -> str:
        """Return URL path to the originating source document."""
        if self.source_type == SourceType.PURCHASE:
            return f"/purchasing/{self.source_id}/"
        if self.source_type in (
            SourceType.PRODUCTION_ISSUE,
            SourceType.PRODUCTION_RECEIPT,
            SourceType.PRODUCTION_REVERSAL,
        ):
            return f"/production/{self.source_id}/"
        if self.source_type == SourceType.ADJUSTMENT:
            return f"/inventory/adjust/{self.source_id}/"
        return f"/inventory/ledger/?source_type={self.source_type}&source_id={self.source_id}"

    def __str__(self) -> str:
        return f"{self.item.sku}: {self.qty} ({self.source_type} #{self.source_id})"


class StockAdjustment(models.Model):
    """Manual inventory adjustment document requiring an explicit reason."""

    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="adjustments",
    )
    input_qty = models.DecimalField(max_digits=14, decimal_places=3)
    input_unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    qty = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Signed quantity converted into item's base unit.",
    )
    unit_rate = models.DecimalField(max_digits=14, decimal_places=6)
    reason = models.TextField()
    adjusted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_adjustments",
    )
    adjusted_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-adjusted_at", "-id"]

    def __str__(self) -> str:
        return f"ADJ-{self.pk} {self.item.sku} {self.qty}"
