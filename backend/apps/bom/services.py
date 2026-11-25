"""BOM seed helper."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.bom.models import BOM, BOMLine
from apps.masters.models import Item, Unit


@transaction.atomic
def seed_benchmark_bom(*, items: dict[str, Item], units: dict[str, Unit]) -> BOM:
    """Idempotently seed the Section 4/5 Murukku 200g BOM."""
    bom, _ = BOM.objects.update_or_create(
        product=items["FG-MURUKKU-200G"],
        name="Murukku 200g Standard Batch",
        defaults={
            "expected_yield": Decimal("200.000"),
            "is_active": True,
            "notes": "Benchmark batch: 200 packets (200g each)",
        },
    )
    line_specs = [
        ("RAW-FLOUR", Decimal("40.000"), "kg"),
        ("RAW-OIL", Decimal("10.000"), "L"),
        ("RAW-SPICE", Decimal("1.200"), "kg"),
        ("PACK-POUCH", Decimal("200.000"), "pcs"),
        ("PACK-CARTON", Decimal("10.000"), "carton"),
    ]
    for sku, qty, unit_code in line_specs:
        BOMLine.objects.update_or_create(
            bom=bom,
            item=items[sku],
            defaults={"qty_per_batch": qty, "unit": units[unit_code]},
        )
    return bom
