"""Phase 7 tests: audit trail coverage, filtering, and read-only enforcement."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.bom.models import BOM
from apps.costing.models import OverheadType
from apps.costing.services import post_overhead
from apps.inventory.services import post_adjustment
from apps.masters.models import Customer, Item, Unit
from apps.payments.services import post_payment
from apps.production.services import create_production_run, post_production_run
from apps.sales.services import (
    approve_order,
    post_credit_note,
    post_dispatch,
    post_invoice,
    submit_order,
)

FG_SKU = "FG-MURUKKU-200G"


@pytest.mark.django_db
def test_write_services_record_audit_entries(seeded_db):
    admin = User.objects.get(username="admin")
    production = User.objects.get(username="production")
    customer = Customer.objects.get(code="CUST-RET-A")
    fg = Item.objects.get(sku=FG_SKU)
    packet = Unit.objects.get(code="packet")

    order = submit_order(
        customer=customer,
        salesman=User.objects.get(username="salesmanA"),
        lines=[{"item": fg, "qty": Decimal("10.000"), "unit": packet, "unit_price": "50.00"}],
    )
    approve_order(order, user=admin)
    invoice = post_invoice(order, user=admin)
    post_dispatch(invoice, user=admin)
    post_payment(customer=customer, amount="100.00", user=admin)

    run = create_production_run(bom=BOM.objects.get(product=fg), user=production)
    post_production_run(run, production)
    post_overhead(
        run=run,
        overhead_type=OverheadType.POWER,
        amount="500.00",
        description="Generator diesel",
        user=production,
    )

    post_adjustment(
        item=Item.objects.get(sku="RAW-SPICE"),
        qty=Decimal("-0.100"),
        unit=Unit.objects.get(code="kg"),
        reason="Moisture loss",
        user=production,
    )
    post_credit_note(invoice, user=admin, reason="Billing correction")

    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {
        "submit_order",
        "approve_order",
        "post_invoice",
        "post_dispatch",
        "post_payment",
        "post_production_run",
        "post_overhead",
        "post_adjustment",
        "post_credit_note",
    } <= actions

    entry = AuditLog.objects.get(action="post_invoice")
    assert entry.user_id == admin.id
    assert entry.model_name == "Invoice"
    assert entry.object_id == invoice.id
    assert invoice.fy_number in entry.after_json

    dispatch_entry = AuditLog.objects.get(action="post_dispatch")
    assert dispatch_entry.model_name == "Dispatch"
    assert "DISP-" in dispatch_entry.notes


@pytest.mark.django_db
def test_audit_log_view_filters_and_role_access(client, seeded_db):
    admin = User.objects.get(username="admin")
    log_action(
        user=admin,
        model_name="Invoice",
        object_id=1,
        action="post_invoice",
        after={"total": "525.00"},
        notes="first",
    )
    log_action(
        user=admin,
        model_name="Order",
        object_id=2,
        action="approve_order",
        after={"status": "approved"},
        notes="second",
    )

    client.login(username="admin", password="benchmark123")
    page = client.get("/audit/")
    assert page.status_code == 200
    assert b"post_invoice" in page.content
    assert b"approve_order" in page.content

    filtered = client.get("/audit/?action=approve")
    assert filtered.status_code == 200
    assert b"approve_order" in filtered.content
    assert b"post_invoice" not in filtered.content

    client.login(username="auditor", password="benchmark123")
    assert client.get("/audit/").status_code == 200

    client.login(username="salesmanA", password="benchmark123")
    assert client.get("/audit/").status_code == 403


@pytest.mark.django_db
def test_auditor_is_read_only_across_sales_and_payments(client, seeded_db):
    admin = User.objects.get(username="admin")
    order = submit_order(
        customer=Customer.objects.get(code="CUST-RET-A"),
        salesman=User.objects.get(username="salesmanA"),
        lines=[
            {
                "item": Item.objects.get(sku=FG_SKU),
                "qty": Decimal("1.000"),
                "unit": Unit.objects.get(code="packet"),
                "unit_price": "50.00",
            }
        ],
    )
    approve_order(order, user=admin)
    invoice = post_invoice(order, user=admin)

    client.login(username="auditor", password="benchmark123")
    assert client.get("/sales/orders/").status_code == 200
    assert client.get(f"/sales/invoices/{invoice.id}/").status_code == 200
    assert client.post(f"/sales/orders/{order.id}/approve/").status_code == 403
    assert client.post(f"/sales/invoices/{invoice.id}/dispatch/").status_code == 403
    assert client.post("/payments/new/", {"amount": "10"}).status_code == 403
