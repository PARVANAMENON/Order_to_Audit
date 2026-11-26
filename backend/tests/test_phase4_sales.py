"""Phase 4 tests: sales orders, approval, GST invoicing, dispatch, credit notes, PWA."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.inventory.models import SourceType, StockLedger
from apps.inventory.services import balance
from apps.masters.models import Customer, Item, Unit
from apps.sales.models import DispatchStatus, InvoiceStatus, Order, OrderStatus
from apps.sales.services import (
    approve_order,
    post_credit_note,
    post_dispatch,
    post_invoice,
    reject_order,
    submit_order,
)

FG_SKU = "FG-MURUKKU-200G"


def _submit(customer_code: str, qty: str = "10.000", price: str = "50.00"):
    customer = Customer.objects.get(code=customer_code)
    salesman = User.objects.get(username="salesmanA")
    return submit_order(
        customer=customer,
        salesman=salesman,
        lines=[
            {
                "item": Item.objects.get(sku=FG_SKU),
                "qty": qty,
                "unit": Unit.objects.get(code="packet"),
                "unit_price": price,
            }
        ],
        notes="Phase 4 test",
    )


def _invoice(customer_code: str, qty: str = "10.000"):
    admin = User.objects.get(username="admin")
    order = _submit(customer_code, qty=qty)
    approve_order(order, user=admin)
    return post_invoice(order, user=admin)


@pytest.mark.django_db
def test_intra_state_invoice_splits_cgst_sgst(seeded_db):
    invoice = _invoice("CUST-RET-A")

    assert invoice.place_of_supply == "Tamil Nadu"
    assert invoice.taxable_value == Decimal("500.00")
    assert invoice.cgst == Decimal("12.50")
    assert invoice.sgst == Decimal("12.50")
    assert invoice.igst == Decimal("0.00")
    assert invoice.total_amount == Decimal("525.00")

    line = invoice.lines.get()
    assert line.hsn == "2106"
    assert line.gst_rate == Decimal("5.00")
    assert line.line_total == Decimal("525.00")

    order = Order.objects.get(pk=invoice.order_id)
    assert order.status == OrderStatus.INVOICED

    # Invoicing is idempotent: same approved order returns the same invoice.
    assert post_invoice(order, user=User.objects.get(username="admin")).pk == invoice.pk


@pytest.mark.django_db
def test_inter_state_invoice_uses_igst(seeded_db):
    invoice = _invoice("CUST-DIST-B")

    assert invoice.place_of_supply == "Karnataka"
    assert invoice.taxable_value == Decimal("500.00")
    assert invoice.cgst == Decimal("0.00")
    assert invoice.sgst == Decimal("0.00")
    assert invoice.igst == Decimal("25.00")
    assert invoice.total_amount == Decimal("525.00")


@pytest.mark.django_db
def test_dispatch_posts_negative_ledger_once_and_credit_note_reverses(seeded_db):
    admin = User.objects.get(username="admin")
    fg = Item.objects.get(sku=FG_SKU)
    invoice = _invoice("CUST-RET-A")
    assert balance(fg) == Decimal("50.000")

    dispatch = post_dispatch(invoice, user=admin)
    assert dispatch.status == DispatchStatus.DISPATCHED
    assert balance(fg) == Decimal("40.000")
    assert StockLedger.objects.filter(source_type=SourceType.DISPATCH).count() == 1

    # Re-posting must not double-deduct stock.
    again = post_dispatch(invoice, user=admin)
    assert again.pk == dispatch.pk
    assert StockLedger.objects.filter(source_type=SourceType.DISPATCH).count() == 1
    assert balance(fg) == Decimal("40.000")

    cn = post_credit_note(
        invoice, user=admin, reason="Customer returned goods", reverses_stock=True
    )
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.CANCELLED
    assert cn.total_amount == Decimal("525.00")
    assert balance(fg) == Decimal("50.000")
    assert StockLedger.objects.filter(source_type=SourceType.CREDIT_NOTE).count() == 1

    with pytest.raises(ValidationError):
        post_credit_note(invoice, user=admin, reason="Duplicate", reverses_stock=True)


@pytest.mark.django_db
def test_rejection_requires_reason_and_blocks_double_transition(seeded_db):
    admin = User.objects.get(username="admin")
    order = _submit("CUST-RET-A")

    with pytest.raises(ValidationError):
        reject_order(order, user=admin, reason="   ")

    rejected = reject_order(order, user=admin, reason="Credit limit exceeded")
    assert rejected.status == OrderStatus.REJECTED
    assert rejected.rejection_reason == "Credit limit exceeded"

    with pytest.raises(ValidationError):
        approve_order(rejected, user=admin)


@pytest.mark.django_db
def test_order_create_view_invoices_approved_order(client, seeded_db):
    client.login(username="salesmanA", password="benchmark123")
    response = client.post(
        "/sales/orders/new/",
        {
            "customer_id": Customer.objects.get(code="CUST-RET-A").id,
            "notes": "View-created order",
            "item_id": [Item.objects.get(sku=FG_SKU).id],
            "qty": ["5"],
            "unit_id": [Unit.objects.get(code="packet").id],
            "unit_price": ["50.00"],
        },
    )
    assert response.status_code == 302
    order = Order.objects.get(notes="View-created order")
    assert order.status == OrderStatus.SUBMITTED

    # Salesmen cannot approve their own orders.
    assert client.post(f"/sales/orders/{order.id}/approve/").status_code == 403

    client.login(username="admin", password="benchmark123")
    detail = client.get(f"/sales/orders/{order.id}/")
    assert detail.status_code == 200
    assert b"adj_qty_" in detail.content

    line = order.lines.get()
    approve = client.post(
        f"/sales/orders/{order.id}/approve/", {f"adj_qty_{line.id}": "2"}
    )
    assert approve.status_code == 302
    order.refresh_from_db()
    assert order.status == OrderStatus.APPROVED
    line.refresh_from_db()
    assert line.approved_qty == Decimal("2.000")
    assert client.get(f"/sales/orders/{order.id}/").status_code == 200

    # The approved quantity, not the ordered quantity, flows into the invoice.
    assert client.post(f"/sales/orders/{order.id}/invoice/").status_code == 302
    order.refresh_from_db()
    assert order.invoice.lines.get().qty == Decimal("2.000")


@pytest.mark.django_db
def test_pwa_api_is_idempotent_and_pwa_shell_served(client, seeded_db):
    client.login(username="salesmanA", password="benchmark123")
    payload = {
        "customer_id": Customer.objects.get(code="CUST-RET-A").id,
        "notes": "Offline retry",
        "idempotency_key": str(uuid.uuid4()),
        "lines": [
            {
                "item_id": Item.objects.get(sku=FG_SKU).id,
                "unit_id": Unit.objects.get(code="packet").id,
                "qty": "3",
                "unit_price": "50.00",
            }
        ],
    }

    first = client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")
    second = client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")
    assert first.status_code == 200
    assert second.status_code == 200
    first_body, second_body = first.json(), second.json()
    assert first_body["created"] is True
    assert second_body["created"] is False
    assert first_body["id"] == second_body["id"]
    assert Order.objects.count() == 1

    page = client.get("/sales/pwa/")
    assert page.status_code == 200
    assert b"Field Order Capture" in page.content

    manifest = client.get("/sales/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/sales/pwa/"

    worker = client.get("/sales/sw.js")
    assert worker.status_code == 200
    assert "application/javascript" in worker["Content-Type"]
    assert worker["Service-Worker-Allowed"] == "/sales/"
    assert b"ota-sales-pwa-v1" in worker.content

    # Auditor is strictly read-only and cannot open the field capture shell.
    client.login(username="auditor", password="benchmark123")
    assert client.get("/sales/pwa/").status_code == 403
    assert client.get("/sales/orders/").status_code == 200
    assert client.get(f"/sales/invoices/{_invoice('CUST-RET-A').id}/").status_code == 200
