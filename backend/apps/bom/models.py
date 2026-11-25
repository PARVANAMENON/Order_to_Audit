"""BOM and BOMLine models."""

from __future__ import annotations

from django.db import models

from apps.masters.models import Item, ItemType, Unit


class BOM(models.Model):
    """Bill of Materials defining expected yield and component quantities per batch."""

    product = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="boms",
        limit_choices_to={"item_type": ItemType.FINISHED},
    )
    name = models.CharField(max_length=120)
    expected_yield = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Expected good output per batch in product's base unit.",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["product__sku", "name"]

    def __str__(self) -> str:
        return f"{self.product.sku} - {self.name} (yield {self.expected_yield})"


class BOMLine(models.Model):
    """Component material/packaging requirement per batch."""

    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="bom_lines",
        limit_choices_to={"item_type__in": [ItemType.RAW, ItemType.PACK]},
    )
    qty_per_batch = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)

    class Meta:
        unique_together = ("bom", "item")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.item.sku}: {self.qty_per_batch} {self.unit.code}"
