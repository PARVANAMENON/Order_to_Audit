"""Phase 1 acceptance tests: unit conversions, seed idempotency, and role permission matrix."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.masters.models import Customer, Item, PriceList, Unit
from apps.masters.services import UnitConversionError, convert_quantity, convert_rate


@pytest.mark.django_db
def test_unit_conversions_kg_g_l_ml_carton_packet(seeded_db):
    kg = Unit.objects.get(code="kg")
    g = Unit.objects.get(code="g")
    litre = Unit.objects.get(code="L")
    ml = Unit.objects.get(code="ml")
    carton = Unit.objects.get(code="carton")
    packet = Unit.objects.get(code="packet")

    assert convert_quantity(Decimal("100"), kg, g) == Decimal("100000.000")
    assert convert_quantity(Decimal("40000"), g, kg) == Decimal("40.000")
    assert convert_quantity(Decimal("10.5"), litre, ml) == Decimal("10500.000")
    assert convert_quantity(Decimal("19500"), ml, litre) == Decimal("19.500")
    assert convert_quantity(Decimal("9"), carton, packet) == Decimal("180.000")
    assert convert_quantity(Decimal("180"), packet, carton) == Decimal("9.000")

    assert convert_rate(Decimal("42.00"), kg, g) == Decimal("0.042000")

    with pytest.raises(UnitConversionError):
        convert_quantity(Decimal("5"), kg, ml)

    with pytest.raises(TypeError):
        convert_quantity(10.5, litre, ml)  # type: ignore[arg-type]


@pytest.mark.django_db
def test_demo_profile_resets_to_clean_baseline(seeded_db):
    from django.apps import apps

    from apps.masters.management.commands.seed_benchmark import Command
    from apps.sales.models import Order
    from apps.sales.services import submit_order

    call_command("seed_benchmark", "--profile", "demo")
    transactional = [apps.get_model(*pair) for pair in Command.TRANSACTION_MODELS]
    baseline = [model.objects.count() for model in transactional]
    assert Order.objects.count() == 2
    assert sum(baseline) > 0

    submit_order(
        customer=Customer.objects.get(code="CUST-RET-A"),
        salesman=seeded_db["salesmanA"],
        lines=[
            {
                "item": Item.objects.get(sku="FG-MURUKKU-200G"),
                "qty": Decimal("5"),
                "unit": Unit.objects.get(code="packet"),
                "unit_price": Decimal("50.00"),
            }
        ],
        notes="Scratch order that the demo reset must remove",
    )
    assert Order.objects.filter(notes__startswith="Scratch order").exists()

    call_command("seed_benchmark", "--profile", "demo")

    assert [model.objects.count() for model in transactional] == baseline
    assert not Order.objects.filter(notes__startswith="Scratch order").exists()
    assert Item.objects.count() == 6
    assert Customer.objects.count() == 2
    assert PriceList.objects.count() == 1


@pytest.mark.django_db
def test_seed_benchmark_is_idempotent(seeded_db):
    call_command("seed_benchmark")

    assert Item.objects.count() == 6
    assert Customer.objects.count() == 2
    assert PriceList.objects.count() == 1

    ret_a = Customer.objects.get(code="CUST-RET-A")
    dist_b = Customer.objects.get(code="CUST-DIST-B")
    assert ret_a.state == "Tamil Nadu"
    assert dist_b.state == "Karnataka"
    assert ret_a.assigned_salesman.username == "salesmanA"
    assert dist_b.assigned_salesman.username == "salesmanB"


@pytest.mark.django_db
def test_role_permission_matrix_and_logins(client, seeded_db):
    # Unauthenticated redirects to login for HTML, 401/403 for DRF API
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login/" in resp.url

    api_unauth = client.get("/masters/api/items/")
    assert api_unauth.status_code in (401, 403)

    # Every seeded role can log in and reach its landing page
    for username in ("salesmanA", "salesmanB", "admin", "production", "auditor", "owner"):
        assert client.login(username=username, password="benchmark123")
        landing = client.get("/")
        assert landing.status_code == 200
        client.logout()

    # Salesman sees only assigned customers in masters customer view & API
    client.login(username="salesmanA", password="benchmark123")
    api_cust = client.get("/masters/api/customers/")
    assert api_cust.status_code == 200
    assert [c["code"] for c in api_cust.json()] == ["CUST-RET-A"]

    # Salesman cannot create items via API (admin only)
    item_post = client.post(
        "/masters/api/items/",
        {"sku": "X", "name": "X", "item_type": "raw", "base_unit": Unit.objects.first().id},
    )
    assert item_post.status_code == 403

    # Auditor can read masters & items API, but cannot write
    client.login(username="auditor", password="benchmark123")
    assert client.get("/masters/items/").status_code == 200
    assert client.get("/masters/api/items/").status_code == 200
    assert (
        client.post(
            "/masters/api/items/",
            {"sku": "Y", "name": "Y", "item_type": "raw", "base_unit": Unit.objects.first().id},
        ).status_code
        == 403
    )

    # Production cannot access supplier write API (admin only), can read items
    client.login(username="production", password="benchmark123")
    assert client.get("/masters/api/items/").status_code == 200
    assert (
        client.post(
            "/masters/api/suppliers/",
            {"code": "SUP-2", "name": "Test", "state": "Tamil Nadu"},
        ).status_code
        == 403
    )

    # Admin can create master item via API
    client.login(username="admin", password="benchmark123")
    g_unit = Unit.objects.get(code="g")
    ok = client.post(
        "/masters/api/items/",
        {
            "sku": "RAW-SALT",
            "name": "Salt",
            "item_type": "raw",
            "base_unit": g_unit.id,
            "hsn": "2501",
            "gst_rate": "0.00",
        },
    )
    assert ok.status_code == 201
