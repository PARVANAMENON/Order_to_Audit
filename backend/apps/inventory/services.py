"""Ledger balance, weighted-average cost (WAC), adjustment, and opening seed services."""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import log_action
from apps.inventory.models import SourceType, StockAdjustment, StockLedger
from apps.masters.models import Item, Unit
from apps.masters.services import (
    QTY_QUANT,
    RATE_QUANT,
    _to_decimal,
    convert_quantity,
    convert_rate,
)


class InsufficientStockError(ValidationError):
    """Raised when a movement would cause stock balance to drop below zero."""


def _filter_as_of(qs, as_of: datetime | date | None):
    if as_of is None:
        return qs
    if isinstance(as_of, datetime):
        return qs.filter(date__lte=as_of)
    return qs.filter(date__date__lte=as_of)


def balance(item: Item, as_of: datetime | date | None = None) -> Decimal:
    """Return current stock balance in `item.base_unit` as SUM(StockLedger.qty)."""
    qs = _filter_as_of(StockLedger.objects.filter(item=item), as_of)
    total = qs.aggregate(total=Coalesce(Sum("qty"), Decimal("0.000")))["total"]
    return Decimal(total).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


def balance_in_unit(
    item: Item,
    unit: Unit | None = None,
    as_of: datetime | date | None = None,
) -> Decimal:
    """Return stock balance converted to `unit` (defaults to `item.preferred_display_unit`)."""
    target_unit = unit or item.preferred_display_unit
    return convert_quantity(balance(item, as_of=as_of), item.base_unit, target_unit)


def get_wac(item: Item, as_of: datetime | date | None = None) -> Decimal:
    """Compute weighted-average cost per `item.base_unit` purely from StockLedger."""
    qs = _filter_as_of(StockLedger.objects.filter(item=item), as_of)
    total_qty = Decimal("0")
    total_value = Decimal("0")
    for row_qty, row_rate in qs.values_list("qty", "unit_rate"):
        total_qty += row_qty
        total_value += row_qty * row_rate
    if total_qty <= 0:
        return Decimal("0.000000")
    return (total_value / total_qty).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def get_wac_in_unit(
    item: Item,
    unit: Unit | None = None,
    as_of: datetime | date | None = None,
) -> Decimal:
    """Return weighted-average cost expressed per `unit` (defaults to display unit)."""
    target_unit = unit or item.preferred_display_unit
    return convert_rate(get_wac(item, as_of=as_of), item.base_unit, target_unit)


@transaction.atomic
def post_adjustment(
    *,
    item: Item,
    qty: Decimal | int | str,
    unit: Unit,
    reason: str,
    user: User,
    unit_rate: Decimal | int | str | None = None,
    adjusted_at: datetime | None = None,
) -> StockAdjustment:
    """Validate and post a manual stock adjustment inside an atomic transaction."""
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValidationError("Reason is mandatory for manual stock adjustments.")

    dec_qty = _to_decimal(qty)
    if dec_qty == 0:
        raise ValidationError("Adjustment quantity cannot be zero.")

    base_qty = convert_quantity(dec_qty, unit, item.base_unit)
    locked_item = Item.objects.select_for_update().get(pk=item.pk)
    current_bal = balance(locked_item)
    if current_bal + base_qty < 0:
        raise InsufficientStockError(
            f"Insufficient stock for {locked_item.sku}: on hand {current_bal} "
            f"{locked_item.base_unit.code}, requested adjustment {base_qty}."
        )

    if unit_rate is not None and str(unit_rate).strip() != "":
        dec_rate = _to_decimal(unit_rate)
        if dec_rate < 0:
            raise ValidationError("Unit rate cannot be negative.")
        base_rate = convert_rate(dec_rate, unit, locked_item.base_unit)
    else:
        base_rate = get_wac(locked_item)

    ts = adjusted_at or timezone.now()
    adj = StockAdjustment.objects.create(
        item=locked_item,
        input_qty=dec_qty.quantize(QTY_QUANT, rounding=ROUND_HALF_UP),
        input_unit=unit,
        qty=base_qty,
        unit_rate=base_rate,
        reason=clean_reason,
        adjusted_by=user,
        adjusted_at=ts,
    )
    StockLedger.objects.create(
        item=locked_item,
        date=ts,
        qty=base_qty,
        unit_rate=base_rate,
        source_type=SourceType.ADJUSTMENT,
        source_id=adj.id,
        source_ref=f"ADJ-{adj.id}",
        user=user,
        notes=clean_reason,
    )
    log_action(
        user=user,
        model_name="StockAdjustment",
        object_id=adj.id,
        action="post_adjustment",
        after={
            "item": locked_item.sku,
            "qty": str(base_qty),
            "unit_rate": str(base_rate),
            "reason": clean_reason,
        },
        notes=f"ADJ-{adj.id} {locked_item.sku}",
    )
    return adj


@transaction.atomic
def seed_opening_balances(
    *,
    items: dict[str, Item],
    units: dict[str, Unit],
    posted_by: User,
) -> None:
    """Idempotently post Section 5 / Section 7 opening stock balances to StockLedger."""
    opening_specs = [
        ("RAW-FLOUR", Decimal("100"), "kg", Decimal("42.00")),
        ("RAW-OIL", Decimal("30"), "L", Decimal("140.00")),
        ("RAW-SPICE", Decimal("5"), "kg", Decimal("200.00")),
        ("PACK-POUCH", Decimal("500"), "pcs", Decimal("2.50")),
        ("PACK-CARTON", Decimal("30"), "carton", Decimal("15.00")),
        ("FG-MURUKKU-200G", Decimal("50"), "packet", Decimal("0.00")),
    ]
    for idx, (sku, qty, unit_code, rate) in enumerate(opening_specs, start=1):
        item = items[sku]
        if StockLedger.objects.filter(item=item, source_type=SourceType.OPENING).exists():
            continue
        unit = units[unit_code]
        base_qty = convert_quantity(qty, unit, item.base_unit)
        base_rate = convert_rate(rate, unit, item.base_unit)
        StockLedger.objects.create(
            item=item,
            date=timezone.now(),
            qty=base_qty,
            unit_rate=base_rate,
            source_type=SourceType.OPENING,
            source_id=idx,
            source_ref=f"OPEN-{sku}",
            user=posted_by,
            notes="Benchmark opening stock balance",
        )
