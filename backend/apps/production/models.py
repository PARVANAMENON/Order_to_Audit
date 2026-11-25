"""ProductionRun and RunLine models."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.bom.models import BOM
from apps.masters.models import Item, Unit
from apps.masters.services import convert_quantity


class ProductionRunStatus(models.TextChoices):
    """Lifecycle states of a production run."""

    DRAFT = "draft", "Draft"
    POSTED = "posted", "Posted"


class ProductionRun(models.Model):
    """Batch production run consuming raw/pack materials and producing finished goods."""

    run_number = models.CharField(max_length=40, unique=True, blank=True)
    bom = models.ForeignKey(BOM, on_delete=models.PROTECT, related_name="runs")
    batches = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal("1.000"))
    run_date = models.DateField(default=timezone.localdate)
    expected_output = models.DecimalField(max_digits=14, decimal_places=3)
    actual_output = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
    )
    wastage = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    damaged_packaging = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
    )
    yield_variance_pct = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    yield_flagged = models.BooleanField(default=False)
    material_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        max_length=16,
        choices=ProductionRunStatus.choices,
        default=ProductionRunStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_runs",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="posted_runs",
        null=True,
        blank=True,
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-run_date", "-id"]

    @property
    def has_flagged_variance(self) -> bool:
        return self.yield_flagged or self.lines.filter(flagged=True).exists()

    def __str__(self) -> str:
        return self.run_number or f"RUN-{self.pk}"


class RunLine(models.Model):
    """Planned vs actual component consumption for a production run."""

    run = models.ForeignKey(ProductionRun, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="run_lines")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Planned consumption in item's base unit.",
    )
    actual_qty = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Actual consumption in item's base unit.",
    )
    variance_pct = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    flagged = models.BooleanField(default=False)
    unit_rate = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    line_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ("run", "item")
        ordering = ["id"]

    @property
    def planned_in_unit(self) -> Decimal:
        """Planned quantity converted to the line's display unit."""
        return convert_quantity(self.planned_qty, self.item.base_unit, self.unit)

    @property
    def actual_in_unit(self) -> Decimal:
        """Actual quantity converted to the line's display unit."""
        return convert_quantity(self.actual_qty, self.item.base_unit, self.unit)

    def __str__(self) -> str:
        return f"{self.run.run_number} - {self.item.sku}"
