"""Phase 3 tests: benchmark steps 1-3, variance flags, re-post reversals, and unit checks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.bom.models import BOM
from apps.inventory.models import SourceType, StockLedger
from apps.inventory.services import (
    InsufficientStockError,
    balance,
    balance_in_unit,
    get_wac_in_unit,
)
from apps.masters.models import Item, Supplier, Unit
from apps.masters.services import UnitConversionError
from apps.production.models import ProductionRunStatus
from apps.production.services import (
    create_production_run,
    post_production_run,
    update_run_actuals,
)
from apps.purchasing.models import Purchase, PurchaseLine
from apps.purchasing.services import post_purchase


@pytest.mark.django_db
def test_benchmark_steps_1_to_3(seeded_db):
    """Benchmark steps 1-3: seed -> purchase 60kg flour -> production run with variances."""
    prod_user = User.objects.get(username="production")
    supplier = Supplier.objects.get(code="SUP-KAVERI")
    kg = Unit.objects.get(code="kg")
    litre = Unit.objects.get(code="L")
    ml = Unit.objects.get(code="ml")
    pcs = Unit.objects.get(code="pcs")
    carton = Unit.objects.get(code="carton")

    flour = Item.objects.get(sku="RAW-FLOUR")
    oil = Item.objects.get(sku="RAW-OIL")
    spice = Item.objects.get(sku="RAW-SPICE")
    pouches = Item.objects.get(sku="PACK-POUCH")
    cartons = Item.objects.get(sku="PACK-CARTON")
    fg = Item.objects.get(sku="FG-MURUKKU-200G")

    # Step 2: Purchase 60 kg flour @ Rs 45/kg -> 160 kg, WAC = 43.125/kg
    purchase = Purchase.objects.create(
        supplier=supplier,
        invoice_number="PUR-BENCH-001",
        date=date(2026, 4, 2),
        created_by=prod_user,
    )
    PurchaseLine.objects.create(
        purchase=purchase,
        item=flour,
        qty=Decimal("60.000"),
        unit=kg,
        unit_rate=Decimal("45.0000"),
    )
    post_purchase(purchase, prod_user)
    assert balance_in_unit(flour, kg) == Decimal("160.000")
    assert get_wac_in_unit(flour, kg) == Decimal("43.125000")

    # Step 3: Production run for 1 batch of Murukku 200g
    bom = BOM.objects.get(product=fg)
    run = create_production_run(
        bom=bom,
        batches=Decimal("1"),
        run_date=date(2026, 4, 3),
        user=prod_user,
    )
    # Oil entered as 10500 ml against ml/L stock, pouches 188 good + 6 damaged = 194
    update_run_actuals(
        run,
        actual_output=Decimal("188"),
        wastage=Decimal("12"),
        damaged_packaging=Decimal("6"),
        line_actuals={
            "RAW-FLOUR": (Decimal("40"), kg),
            "RAW-OIL": (Decimal("10500"), ml),
            "RAW-SPICE": (Decimal("1.2"), kg),
            "PACK-POUCH": (Decimal("194"), pcs),
            "PACK-CARTON": (Decimal("9"), carton),
        },
    )
    post_production_run(run, prod_user)
    run.refresh_from_db()

    # Verify closing balances
    assert balance_in_unit(flour, kg) == Decimal("120.000")
    assert balance_in_unit(oil, litre) == Decimal("19.500")
    assert balance_in_unit(spice, kg) == Decimal("3.800")
    assert balance(pouches) == Decimal("306.000")
    assert balance(cartons) == Decimal("21.000")
    assert balance(fg) == Decimal("238.000")

    # Verify yield and line variances
    assert run.status == ProductionRunStatus.POSTED
    assert run.yield_variance_pct == Decimal("-6.00")
    assert run.yield_flagged is True

    lines_by_sku = {line.item.sku: line for line in run.lines.select_related("item").all()}
    assert lines_by_sku["RAW-FLOUR"].variance_pct == Decimal("0.00")
    assert lines_by_sku["RAW-FLOUR"].flagged is False
    assert lines_by_sku["RAW-FLOUR"].line_cost == Decimal("1725.00")

    assert lines_by_sku["RAW-OIL"].variance_pct == Decimal("5.00")
    assert lines_by_sku["RAW-OIL"].flagged is True
    assert lines_by_sku["RAW-OIL"].line_cost == Decimal("1470.00")

    assert lines_by_sku["RAW-SPICE"].variance_pct == Decimal("0.00")
    assert lines_by_sku["RAW-SPICE"].flagged is False
    assert lines_by_sku["RAW-SPICE"].line_cost == Decimal("240.00")

    # 194 vs 200 = -3.00% -> within default 3.00% tolerance (abs(-3) > 3 is False)
    assert lines_by_sku["PACK-POUCH"].variance_pct == Decimal("-3.00")
    assert lines_by_sku["PACK-POUCH"].flagged is False
    assert lines_by_sku["PACK-POUCH"].line_cost == Decimal("485.00")

    # 9 vs 10 = -10.00% -> exceeds 3.00% tolerance, so flagged
    assert lines_by_sku["PACK-CARTON"].variance_pct == Decimal("-10.00")
    assert lines_by_sku["PACK-CARTON"].flagged is True
    assert lines_by_sku["PACK-CARTON"].line_cost == Decimal("135.00")

    # Total material cost = 1725 + 1470 + 240 + 485 + 135 = 4055.00
    assert run.material_cost == Decimal("4055.00")


@pytest.mark.django_db
def test_reposting_run_reverses_old_rows_and_writes_new_ones(seeded_db):
    prod_user = User.objects.get(username="production")
    fg = Item.objects.get(sku="FG-MURUKKU-200G")
    flour = Item.objects.get(sku="RAW-FLOUR")
    kg = Unit.objects.get(code="kg")
    bom = BOM.objects.get(product=fg)

    run = create_production_run(bom=bom, batches=Decimal("1"), user=prod_user)
    update_run_actuals(
        run,
        actual_output=Decimal("200"),
        line_actuals={"RAW-FLOUR": (Decimal("40"), kg)},
    )
    post_production_run(run, prod_user)
    initial_ledger_count = StockLedger.objects.filter(
        source_id=run.id,
        source_type__in=[SourceType.PRODUCTION_ISSUE, SourceType.PRODUCTION_RECEIPT],
    ).count()
    assert initial_ledger_count == 6
    assert balance_in_unit(flour, kg) == Decimal("60.000")
    assert balance(fg) == Decimal("250.000")

    # Edit run: flour 41 kg, output 196 packets, and re-post
    update_run_actuals(
        run,
        actual_output=Decimal("196"),
        line_actuals={"RAW-FLOUR": (Decimal("41"), kg)},
    )
    post_production_run(run, prod_user, repost=True)

    # Old rows were never deleted; reversal rows + new rows were appended
    assert (
        StockLedger.objects.filter(
            source_id=run.id, source_type=SourceType.PRODUCTION_REVERSAL
        ).count()
        == initial_ledger_count
    )
    assert balance_in_unit(flour, kg) == Decimal("59.000")
    assert balance(fg) == Decimal("246.000")


@pytest.mark.django_db
def test_unit_mismatch_rejected_and_per_item_tolerance_override(seeded_db):
    prod_user = User.objects.get(username="production")
    fg = Item.objects.get(sku="FG-MURUKKU-200G")
    oil = Item.objects.get(sku="RAW-OIL")
    kg = Unit.objects.get(code="kg")
    ml = Unit.objects.get(code="ml")
    bom = BOM.objects.get(product=fg)

    run = create_production_run(bom=bom, batches=Decimal("1"), user=prod_user)

    # Issuing kg against oil (ml/L) must be rejected
    with pytest.raises(UnitConversionError):
        update_run_actuals(
            run,
            actual_output=Decimal("200"),
            line_actuals={"RAW-OIL": (Decimal("10.5"), kg)},
        )

    # Issuing 10500 ml when oil has a 6% tolerance override should NOT flag +5%
    oil.tolerance_pct = Decimal("6.00")
    oil.save()
    update_run_actuals(
        run,
        actual_output=Decimal("200"),
        line_actuals={"RAW-OIL": (Decimal("10500"), ml)},
    )
    post_production_run(run, prod_user)
    oil_line = run.lines.get(item=oil)
    assert oil_line.variance_pct == Decimal("5.00")
    assert oil_line.flagged is False


@pytest.mark.django_db
def test_production_run_blocks_insufficient_stock_and_auditor_write(client, seeded_db):
    prod_user = User.objects.get(username="production")
    fg = Item.objects.get(sku="FG-MURUKKU-200G")
    bom = BOM.objects.get(product=fg)

    # 3 batches require 120 kg flour, but only 100 kg opening stock exists
    run = create_production_run(bom=bom, batches=Decimal("3"), user=prod_user)
    with pytest.raises(InsufficientStockError):
        post_production_run(run, prod_user)

    # Auditor can view production list/detail, but cannot create or post runs
    client.login(username="auditor", password="benchmark123")
    assert client.get("/production/").status_code == 200
    assert client.get(f"/production/{run.id}/").status_code == 200
    assert client.get("/production/new/").status_code == 403
    assert client.post(f"/production/{run.id}/post/", {"actual_output": "200"}).status_code == 403
