"""Phase 6 tests: dashboard, sales/GST/purchase/variance/stock/dues reports and CSV export."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.masters.models import Customer, Item, Supplier, Unit
from apps.purchasing.models import Purchase, PurchaseLine
from apps.purchasing.services import post_purchase
from apps.sales.services import approve_order, post_invoice, submit_order

FG_SKU = "FG-MURUKKU-200G"


def _invoice(customer_code: str = "CUST-RET-A"):
    admin = User.objects.get(username="admin")
    order = submit_order(
        customer=Customer.objects.get(code=customer_code),
        salesman=User.objects.get(username="salesmanA"),
        lines=[
            {
                "item": Item.objects.get(sku=FG_SKU),
                "qty": Decimal("10.000"),
                "unit": Unit.objects.get(code="packet"),
                "unit_price": Decimal("50.00"),
            }
        ],
    )
    approve_order(order, user=admin)
    return post_invoice(order, user=admin)


def _posted_purchase():
    production = User.objects.get(username="production")
    purchase = Purchase.objects.create(
        supplier=Supplier.objects.get(code="SUP-KAVERI"),
        invoice_number="REG-001",
        date=date.today(),
        created_by=production,
    )
    PurchaseLine.objects.create(
        purchase=purchase,
        item=Item.objects.get(sku="RAW-FLOUR"),
        qty=Decimal("10.000"),
        unit=Unit.objects.get(code="kg"),
        unit_rate=Decimal("45.0000"),
    )
    return post_purchase(purchase, production)


@pytest.mark.django_db
def test_reports_render_for_admin_and_export_csv(client, seeded_db):
    invoice = _invoice()
    purchase = _posted_purchase()
    fg = Item.objects.get(sku=FG_SKU)

    client.login(username="admin", password="benchmark123")

    assert client.get("/reports/").status_code == 200

    sales = client.get("/reports/sales/")
    assert sales.status_code == 200
    assert invoice.fy_number.encode() in sales.content

    export = client.get("/reports/sales/?export=csv")
    assert export.status_code == 200
    assert export["Content-Type"].startswith("text/csv")
    assert b"Invoice No" in export.content
    assert invoice.fy_number.encode() in export.content

    gst = client.get("/reports/gst/")
    assert gst.status_code == 200
    assert b"12.50" in gst.content  # CGST and SGST each
    assert b"525.00" in gst.content

    purchases = client.get("/reports/purchases/")
    assert purchases.status_code == 200
    assert f"PUR-{purchase.id}".encode() in purchases.content

    assert client.get("/reports/production/").status_code == 200
    assert client.get("/reports/stock/?item_id=" + str(fg.id)).status_code == 200
    assert client.get("/reports/stock/").status_code == 200

    outstanding = client.get("/reports/outstanding/")
    assert outstanding.status_code == 200
    assert b"Retailer A" in outstanding.content
    assert b"525.00" in outstanding.content


@pytest.mark.django_db
def test_report_roles_and_dashboard_visibility(client, seeded_db):
    _invoice()

    client.login(username="auditor", password="benchmark123")
    for url in (
        "/reports/",
        "/reports/sales/",
        "/reports/gst/",
        "/reports/purchases/",
        "/reports/production/",
        "/reports/stock/",
        "/reports/outstanding/",
    ):
        assert client.get(url).status_code == 200, url

    client.login(username="production", password="benchmark123")
    assert client.get("/reports/").status_code == 200
    assert client.get("/reports/sales/").status_code == 403

    client.login(username="salesmanA", password="benchmark123")
    assert client.get("/reports/").status_code == 200
    assert client.get("/reports/sales/").status_code == 403
    assert client.get("/reports/outstanding/").status_code == 403
