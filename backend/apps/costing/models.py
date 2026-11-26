"""OverheadEntry model for per-run and per-month overheads."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.production.models import ProductionRun


class OverheadType(models.TextChoices):
    LABOUR = "labour", "Labour"
    POWER = "power", "Power / Electricity"
    GAS = "gas", "Gas / Fuel"
    OTHER = "other", "Other"


class OverheadEntry(models.Model):
    """Overhead cost attached to a production run or a calendar month."""

    overhead_type = models.CharField(max_length=16, choices=OverheadType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # Either run-level or monthly
    run = models.ForeignKey(
        ProductionRun,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="overheads",
    )
    month = models.DateField(
        null=True, blank=True, help_text="First day of the month for monthly overheads"
    )
    description = models.CharField(max_length=160, blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="overhead_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        ref = f"RUN-{self.run_id}" if self.run_id else str(self.month)
        return f"{self.overhead_type} Rs{self.amount} [{ref}]"
