"""Phase 5 tests: customer payments, overdue ageing, and overhead cost per packet."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.bom.models import BOM
from apps.costing.models import OverheadType
from apps.costing.services import cost_per_packet, post_overhead, run_overhead_total
from apps.masters.models import Customer, Item, Unit
from apps.payments.models import PaymentAllocation
from apps.payments.services import (
    ageing_buckets,
    customer_outstanding,
    outstanding_for_invoice,
    post_payment,
)
from apps.production.services import create_production_run, post_production_run
from apps.sales.services import approve_order, post_invoice, submit_order

FG_SKU = "FG-MURUKKU-200G"


def _invoice(customer_code: str, qty: str = "10.000"):
    admin = User.objects.get(username="admin")
    order = submit_order(
        customer=Customer.objects.get(code=customer_code),
        salesman=User.objects.get(username="salesmanA"),
        lines=[
            {
                "item": Item.objects.get(sku=FG_SKU),
                "qty": qty,
                "unit": Unit.objects.get(code="packet"),
                "unit_price": Decimal("50.00"),
            }
        ],
    )
    approve_order(order, user=admin)
    return post_invoice(order, user=admin)


def _posted_run(actual_output: str = "200"):
    production = User.objects.get(username="production")
    run = create_production_run(
        bom=BOM.objects.get(product=Item.objects.get(sku=FG_SKU)),
        batches=Decimal("1"),
        user=production,
    )
    run.actual_output = Decimal(actual_output)
    run.save(update_fields=["actual_output"])
    return post_production_run(run, production)


@pytest.mark.django_db
def test_payment_auto_allocates_fifo_and_updates_ageing(seeded_db):
    admin = User.objects.get(username="admin")
    customer = Customer.objects.get(code="CUST-RET-A")
    invoice = _invoice("CUST-RET-A")
    assert invoice.total_amount == Decimal("525.00")

    payment = post_payment(customer=customer, amount="200.00", reference="NEFT-1", user=admin)
    assert payment.amount == Decimal("200.00")
    allocation = PaymentAllocation.objects.get(payment=payment)
    assert allocation.invoice_id == invoice.id
    assert allocation.amount == Decimal("200.00")

    assert outstanding_for_invoice(invoice) == Decimal("325.00")
    assert customer_outstanding(customer) == Decimal("325.00")
    assert ageing_buckets(customer)["0_30"] == Decimal("325.00")
    assert ageing_buckets(customer)["90_plus"] == Decimal("0.00")

    # Overpayment beyond the invoice leaves an unallocated remainder, not a negative due.
    post_payment(customer=customer, amount="400.00", user=admin)
    assert customer_outstanding(customer) == Decimal("0.00")


@pytest.mark.django_db
def test_payment_allocation_rejects_foreign_invoice_and_overallocation(seeded_db):
    admin = User.objects.get(username="admin")
    retail_invoice = _invoice("CUST-RET-A")
    distributor_invoice = _invoice("CUST-DIST-B")
    retailer = Customer.objects.get(code="CUST-RET-A")

    with pytest.raises(ValidationError):
        post_payment(
            customer=retailer,
            amount="100.00",
            allocations=[{"invoice_id": distributor_invoice.id, "amount": "100.00"}],
            user=admin,
        )

    with pytest.raises(ValidationError):
        post_payment(
            customer=retailer,
            amount="600.00",
            allocations=[{"invoice_id": retail_invoice.id, "amount": "600.00"}],
            user=admin,
        )

    with pytest.raises(ValidationError):
        post_payment(customer=retailer, amount="0.00", user=admin)


@pytest.mark.django_db
def test_overhead_costing_computes_cost_per_packet_and_margin(seeded_db):
    production = User.objects.get(username="production")
    run = _posted_run(actual_output="200")

    entry = post_overhead(
        run=run,
        overhead_type=OverheadType.LABOUR,
        amount="2000.00",
        description="Two operators",
        user=production,
    )
    assert entry.amount == Decimal("2000.00")
    assert run_overhead_total(run) == Decimal("2000.00")

    breakdown = cost_per_packet(run)
    expected_total = (run.material_cost + Decimal("2000.00")).quantize(Decimal("0.01"))
    expected_cpp = (expected_total / Decimal("200")).quantize(Decimal("0.01"))

    assert breakdown["material_cost"] == run.material_cost
    assert breakdown["overhead"] == Decimal("2000.00")
    assert breakdown["total_cost"] == expected_total
    assert breakdown["good_packets"] == Decimal("200.000")
    assert breakdown["cost_per_packet"] == expected_cpp
    # Seed price list: Rs 50 per packet.
    assert breakdown["selling_price"] == Decimal("50.00")
    assert breakdown["margin"] == (Decimal("50.00") - expected_cpp).quantize(Decimal("0.01"))
    assert breakdown["margin_pct"] == (
        breakdown["margin"] / Decimal("50.00") * Decimal("100")
    ).quantize(Decimal("0.01"))


@pytest.mark.django_db
def test_overhead_rejects_invalid_type_and_non_positive_amount(seeded_db):
    production = User.objects.get(username="production")
    run = _posted_run()

    with pytest.raises(ValidationError):
        post_overhead(run=run, overhead_type="rent", amount="100.00", user=production)

    with pytest.raises(ValidationError):
        post_overhead(
            run=run, overhead_type=OverheadType.POWER, amount="0.00", user=production
        )


@pytest.mark.django_db
def test_payment_views_enforce_roles(client, seeded_db):
    client.login(username="auditor", password="benchmark123")
    assert client.get("/payments/").status_code == 200
    assert client.post("/payments/new/", {"amount": "10"}).status_code == 403

    client.login(username="admin", password="benchmark123")
    assert client.get("/payments/new/").status_code == 200

    client.login(username="salesmanA", password="benchmark123")
    assert client.get("/payments/").status_code == 403
