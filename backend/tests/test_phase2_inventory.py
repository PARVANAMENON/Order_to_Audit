"""Phase 2 acceptance tests: ledger balances, WAC, purchasing, and manual adjustments."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.accounts.models import User
from apps.inventory.models import StockLedger
from apps.inventory.services import (
    InsufficientStockError,
    balance,
    balance_in_unit,
    get_wac_in_unit,
    post_adjustment,
)
from apps.masters.models import Item, Supplier, Unit
from apps.purchasing.models import Purchase, PurchaseLine
from apps.purchasing.services import post_purchase


@pytest.mark.django_db
def test_no_stored_balance_column_on_item():
    field_names = {f.name for f in Item._meta.get_fields()}
    assert "balance" not in field_names
    assert "stock" not in field_names
    assert "on_hand" not in field_names


@pytest.mark.django_db
def test_opening_balances_and_seed_idempotency(seeded_db):
    call_command("seed_benchmark")

    flour = Item.objects.get(sku="RAW-FLOUR")
    oil = Item.objects.get(sku="RAW-OIL")
    spice = Item.objects.get(sku="RAW-SPICE")
    pouches = Item.objects.get(sku="PACK-POUCH")
    cartons = Item.objects.get(sku="PACK-CARTON")
    fg = Item.objects.get(sku="FG-MURUKKU-200G")

    kg = Unit.objects.get(code="kg")
    litre = Unit.objects.get(code="L")

    assert balance_in_unit(flour, kg) == Decimal("100.000")
    assert balance_in_unit(oil, litre) == Decimal("30.000")
    assert balance_in_unit(spice, kg) == Decimal("5.000")
    assert balance(pouches) == Decimal("500.000")
    assert balance(cartons) == Decimal("30.000")
    assert balance(fg) == Decimal("50.000")

    assert get_wac_in_unit(flour, kg) == Decimal("42.000000")
    assert get_wac_in_unit(oil, litre) == Decimal("140.000000")


@pytest.mark.django_db
def test_purchase_60kg_flour_updates_balance_and_wac(seeded_db):
    prod_user = User.objects.get(username="production")
    supplier = Supplier.objects.get(code="SUP-KAVERI")
    flour = Item.objects.get(sku="RAW-FLOUR")
    kg = Unit.objects.get(code="kg")

    purchase = Purchase.objects.create(
        supplier=supplier,
        invoice_number="KAV-2026-001",
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
    # Re-posting must be idempotent
    post_purchase(purchase, prod_user)

    assert balance_in_unit(flour, kg) == Decimal("160.000")
    assert balance(flour) == Decimal("160000.000")
    assert get_wac_in_unit(flour, kg) == Decimal("43.125000")
    assert StockLedger.objects.filter(source_type="purchase", source_id=purchase.id).count() == 1


@pytest.mark.django_db
def test_manual_adjustment_requires_reason_and_blocks_negative_stock(seeded_db):
    prod_user = User.objects.get(username="production")
    spice = Item.objects.get(sku="RAW-SPICE")
    kg = Unit.objects.get(code="kg")

    with pytest.raises(ValidationError):
        post_adjustment(
            item=spice,
            qty=Decimal("-1.000"),
            unit=kg,
            reason="   ",
            user=prod_user,
        )

    with pytest.raises(InsufficientStockError):
        post_adjustment(
            item=spice,
            qty=Decimal("-10.000"),
            unit=kg,
            reason="Over-deduction test",
            user=prod_user,
        )

    adj = post_adjustment(
        item=spice,
        qty=Decimal("-0.500"),
        unit=kg,
        reason="Moisture loss verified",
        user=prod_user,
    )
    assert adj.qty == Decimal("-500.000")
    assert balance_in_unit(spice, kg) == Decimal("4.500")


@pytest.mark.django_db
def test_phase2_permissions_for_views(client, seeded_db):
    # Salesman and auditor cannot post manual adjustments
    client.login(username="auditor", password="benchmark123")
    assert client.get("/inventory/").status_code == 200
    assert client.get("/inventory/ledger/").status_code == 200
    assert client.get("/purchasing/").status_code == 200
    assert client.get("/inventory/adjust/").status_code == 403
    assert client.get("/purchasing/new/").status_code == 403

    client.login(username="salesmanA", password="benchmark123")
    assert client.get("/inventory/").status_code == 403
    assert client.get("/purchasing/").status_code == 403

    # Production can view summary, ledger, and post purchase via view
    client.login(username="production", password="benchmark123")
    assert client.get("/inventory/").status_code == 200
    assert client.get("/purchasing/new/").status_code == 200
