"""Master data models: Unit, UnitConversion, Item, Customer, Supplier, PriceList."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class Unit(models.Model):
    """Measurement unit (base or transactional)."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=64)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class UnitConversion(models.Model):
    """Table-driven unit conversion factor: 1 from_unit = factor * to_unit."""

    from_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="conversions_from",
    )
    to_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="conversions_to",
    )
    factor = models.DecimalField(max_digits=14, decimal_places=6)

    class Meta:
        unique_together = ("from_unit", "to_unit")
        ordering = ["from_unit__code", "to_unit__code"]

    def __str__(self) -> str:
        return f"1 {self.from_unit.code} = {self.factor} {self.to_unit.code}"


class ItemType(models.TextChoices):
    """Supported item categories."""

    RAW = "raw", "Raw Material"
    PACK = "pack", "Packaging Material"
    FINISHED = "finished", "Finished Goods"


class Item(models.Model):
    """Inventory item across raw, packaging, and finished goods."""

    sku = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    item_type = models.CharField(max_length=16, choices=ItemType.choices)
    base_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="base_items",
    )
    display_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="display_items",
        null=True,
        blank=True,
    )
    hsn = models.CharField(max_length=16, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tolerance_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional per-item variance tolerance %. Defaults to global 3%.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["item_type", "sku"]

    @property
    def effective_tolerance_pct(self) -> Decimal:
        """Return item override tolerance or global default tolerance %."""
        if self.tolerance_pct is not None:
            return self.tolerance_pct
        return Decimal(str(getattr(settings, "DEFAULT_TOLERANCE_PCT", "3.00")))

    @property
    def preferred_display_unit(self) -> Unit:
        """Return display_unit if configured, else base_unit."""
        return self.display_unit or self.base_unit

    def __str__(self) -> str:
        return f"{self.sku} - {self.name}"


class Customer(models.Model):
    """B2B buyer / retailer / distributor."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    gstin = models.CharField(max_length=20, blank=True)
    state = models.CharField(max_length=64)
    assigned_salesman = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_customers",
    )
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.state})"


class Supplier(models.Model):
    """Raw and packaging material vendor."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    gstin = models.CharField(max_length=20, blank=True)
    state = models.CharField(max_length=64)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PriceList(models.Model):
    """Selling price list (default when customer is null, or customer override)."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="prices")
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="prices",
    )
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-effective_from", "item__sku"]

    def __str__(self) -> str:
        target = self.customer.name if self.customer else "Default"
        return f"{self.item.sku} [{target}] @ {self.rate}/{self.unit.code}"
