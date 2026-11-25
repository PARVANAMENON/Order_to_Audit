"""Production run creation, variance engine, atomic ledger posting, and re-posting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.bom.models import BOM
from apps.inventory.models import SourceType, StockLedger
from apps.inventory.services import InsufficientStockError, balance, get_wac
from apps.masters.models import Item, Unit
from apps.masters.services import QTY_QUANT, RATE_QUANT, _to_decimal, convert_quantity
from apps.production.models import ProductionRun, ProductionRunStatus, RunLine

MONEY_QUANT = Decimal("0.01")
PCT_QUANT = Decimal("0.01")


def compute_variance(
    planned: Decimal,
    actual: Decimal,
    tolerance_pct: Decimal,
) -> tuple[Decimal, bool]:
    """Return `(variance_pct, flagged)` where variance = (actual - planned) / planned * 100."""
    if planned == 0:
        pct = Decimal("0.00")
        return pct, actual != 0
    pct = (((actual - planned) / planned) * Decimal("100")).quantize(
        PCT_QUANT, rounding=ROUND_HALF_UP
    )
    flagged = abs(pct) > tolerance_pct
    return pct, flagged


@transaction.atomic
def create_production_run(
    *,
    bom: BOM,
    user: User,
    batches: Decimal | int | str = Decimal("1"),
    run_date: date | None = None,
    notes: str = "",
) -> ProductionRun:
    """Create a draft ProductionRun with RunLines scaled from the BOM."""
    dec_batches = _to_decimal(batches)
    if dec_batches <= 0:
        raise ValidationError("Batches must be greater than zero.")

    bom_lines = list(bom.lines.select_related("item", "item__base_unit", "unit").all())
    if not bom_lines:
        raise ValidationError("BOM has no component lines.")

    expected_output = (bom.expected_yield * dec_batches).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
    run = ProductionRun.objects.create(
        bom=bom,
        batches=dec_batches.quantize(QTY_QUANT, rounding=ROUND_HALF_UP),
        run_date=run_date or timezone.localdate(),
        expected_output=expected_output,
        actual_output=expected_output,
        created_by=user,
        notes=notes,
    )
    run.run_number = f"RUN-{run.id:04d}"
    run.save(update_fields=["run_number"])

    for bom_line in bom_lines:
        planned_base = convert_quantity(
            bom_line.qty_per_batch * dec_batches,
            bom_line.unit,
            bom_line.item.base_unit,
        )
        RunLine.objects.create(
            run=run,
            item=bom_line.item,
            unit=bom_line.unit,
            planned_qty=planned_base,
            actual_qty=planned_base,
        )
    return run


@transaction.atomic
def update_run_actuals(
    run: ProductionRun,
    *,
    actual_output: Decimal | int | str,
    wastage: Decimal | int | str = Decimal("0"),
    damaged_packaging: Decimal | int | str = Decimal("0"),
    line_actuals: Mapping[int | str, tuple[Decimal | int | str, Unit]] | None = None,
    notes: str | None = None,
) -> ProductionRun:
    """Update actual output, wastage, damaged packaging, and component actuals.

    `line_actuals` maps either RunLine.id, Item.id, or Item.sku to `(qty, unit)`.
    Quantities are validated and converted to each item's base unit via UnitConversion;
    incompatible units raise `UnitConversionError`.
    """
    locked_run = ProductionRun.objects.select_for_update().get(pk=run.pk)
    dec_output = _to_decimal(actual_output).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
    dec_wastage = _to_decimal(wastage).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
    dec_damaged = _to_decimal(damaged_packaging).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)

    if dec_output < 0 or dec_wastage < 0 or dec_damaged < 0:
        raise ValidationError("Output, wastage, and damaged packaging cannot be negative.")

    locked_run.actual_output = dec_output
    locked_run.wastage = dec_wastage
    locked_run.damaged_packaging = dec_damaged
    if notes is not None:
        locked_run.notes = notes
    locked_run.save(update_fields=["actual_output", "wastage", "damaged_packaging", "notes"])

    if line_actuals:
        lines = list(locked_run.lines.select_related("item", "item__base_unit", "unit").all())
        for line in lines:
            lookup = None
            if line.id in line_actuals:
                lookup = line_actuals[line.id]
            elif line.item_id in line_actuals:
                lookup = line_actuals[line.item_id]
            elif line.item.sku in line_actuals:
                lookup = line_actuals[line.item.sku]

            if lookup is None:
                continue

            qty_val, input_unit = lookup
            dec_qty = _to_decimal(qty_val)
            if dec_qty < 0:
                raise ValidationError(f"Actual quantity for {line.item.sku} cannot be negative.")
            base_qty = convert_quantity(dec_qty, input_unit, line.item.base_unit)
            line.actual_qty = base_qty
            line.save(update_fields=["actual_qty"])

    return locked_run


def _reverse_existing_run_ledger(run: ProductionRun, user: User, movement_dt: datetime) -> None:
    """Append reversing ledger rows for all net active movements of `run`."""
    existing = StockLedger.objects.filter(
        source_id=run.id,
        source_type__in=[
            SourceType.PRODUCTION_ISSUE,
            SourceType.PRODUCTION_RECEIPT,
            SourceType.PRODUCTION_REVERSAL,
        ],
    ).values_list("item_id", "unit_rate", "qty")

    net_by_item_rate: dict[tuple[int, Decimal], Decimal] = defaultdict(lambda: Decimal("0.000"))
    for item_id, unit_rate, qty in existing:
        net_by_item_rate[(item_id, unit_rate)] += qty

    for (item_id, unit_rate), net_qty in net_by_item_rate.items():
        if net_qty == Decimal("0.000"):
            continue
        StockLedger.objects.create(
            item_id=item_id,
            date=movement_dt,
            qty=-net_qty,
            unit_rate=unit_rate,
            source_type=SourceType.PRODUCTION_REVERSAL,
            source_id=run.id,
            source_ref=run.run_number,
            user=user,
            notes=f"Reversal for re-posted {run.run_number}",
        )


@transaction.atomic
def post_production_run(
    run: ProductionRun,
    user: User,
    *,
    repost: bool = False,
) -> ProductionRun:
    """Post or re-post a ProductionRun inside a single atomic transaction.

    Issues raw and packaging materials at current weighted-average cost (WAC),
    computes per-line and yield variances against item/default tolerances,
    and receives good finished-goods packets into StockLedger.
    When `repost=True` on an already-posted run, old ledger rows are reversed
    via `PRODUCTION_REVERSAL` entries (never edited or deleted) before writing new rows.
    """
    locked_run = (
        ProductionRun.objects.select_for_update()
        .select_related("bom", "bom__product", "bom__product__base_unit")
        .get(pk=run.pk)
    )

    if locked_run.status == ProductionRunStatus.POSTED and not repost:
        return locked_run

    lines = list(locked_run.lines.select_related("item", "item__base_unit", "unit").order_by("id"))
    if not lines:
        raise ValidationError("Cannot post a production run without component lines.")

    fg_item = locked_run.bom.product
    all_item_ids = sorted({line.item_id for line in lines} | {fg_item.pk})
    locked_items = {
        it.pk: it
        for it in Item.objects.select_for_update().filter(id__in=all_item_ids).order_by("id")
    }

    movement_dt = timezone.make_aware(
        datetime.combine(locked_run.run_date, time(15, 0)),
        timezone.get_current_timezone(),
    )

    if locked_run.status == ProductionRunStatus.POSTED and repost:
        _reverse_existing_run_ledger(locked_run, user, movement_dt)

    total_material_cost = Decimal("0.00")

    for line in lines:
        item = locked_items[line.item_id]
        if line.actual_qty < 0:
            raise ValidationError(f"Actual quantity for {item.sku} cannot be negative.")

        on_hand = balance(item)
        if on_hand < line.actual_qty:
            raise InsufficientStockError(
                f"Insufficient stock for {item.sku}: available {on_hand} "
                f"{item.base_unit.code}, required {line.actual_qty} {item.base_unit.code}."
            )

        wac = get_wac(item)
        line_cost = (line.actual_qty * wac).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        variance_pct, flagged = compute_variance(
            line.planned_qty,
            line.actual_qty,
            item.effective_tolerance_pct,
        )

        if line.actual_qty > 0:
            StockLedger.objects.create(
                item=item,
                date=movement_dt,
                qty=-line.actual_qty,
                unit_rate=wac,
                source_type=SourceType.PRODUCTION_ISSUE,
                source_id=locked_run.id,
                source_ref=locked_run.run_number,
                user=user,
                notes=f"Issued to {locked_run.run_number}",
            )

        line.unit_rate = wac
        line.line_cost = line_cost
        line.variance_pct = variance_pct
        line.flagged = flagged
        line.save(update_fields=["unit_rate", "line_cost", "variance_pct", "flagged"])
        total_material_cost += line_cost

    locked_fg = locked_items[fg_item.pk]
    yield_variance_pct, yield_flagged = compute_variance(
        locked_run.expected_output,
        locked_run.actual_output,
        locked_fg.effective_tolerance_pct,
    )

    if locked_run.actual_output > 0:
        fg_unit_rate = (total_material_cost / locked_run.actual_output).quantize(
            RATE_QUANT, rounding=ROUND_HALF_UP
        )
        StockLedger.objects.create(
            item=locked_fg,
            date=movement_dt,
            qty=locked_run.actual_output,
            unit_rate=fg_unit_rate,
            source_type=SourceType.PRODUCTION_RECEIPT,
            source_id=locked_run.id,
            source_ref=locked_run.run_number,
            user=user,
            notes=f"Good FG output from {locked_run.run_number}",
        )

    locked_run.material_cost = total_material_cost.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    locked_run.yield_variance_pct = yield_variance_pct
    locked_run.yield_flagged = yield_flagged
    locked_run.status = ProductionRunStatus.POSTED
    locked_run.posted_by = user
    locked_run.posted_at = timezone.now()
    locked_run.save(
        update_fields=[
            "material_cost",
            "yield_variance_pct",
            "yield_flagged",
            "status",
            "posted_by",
            "posted_at",
        ]
    )
    return locked_run
