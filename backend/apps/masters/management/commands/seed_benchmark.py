"""Idempotent seed command for benchmark master data and test logins."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.masters.models import (
    Customer,
    Item,
    ItemType,
    PriceList,
    Supplier,
    Unit,
    UnitConversion,
)


class Command(BaseCommand):
    """Load Section 5 / Section 7 benchmark master data, logins, opening stock, and BOM."""

    help = "Idempotently seed benchmark masters, test users, opening balances, and BOM."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--profile",
            choices=("benchmark", "demo"),
            default="benchmark",
            help=(
                "benchmark (default): masters, users, opening stock and BOM only. "
                "demo: wipe all transactional documents first, then seed the same "
                "masters plus the demo purchase, production run, orders and payment."
            ),
        )
        parser.add_argument(
            "--demo",
            action="store_true",
            help=(
                "Also seed demo purchase, production run, sales order and payment "
                "documents so every screen has data. Off by default so tests and "
                "clean installs start from opening balances only."
            ),
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Delete every transactional document (orders, invoices, dispatches, "
                "credit notes, payments, production runs, purchases, stock movements, "
                "adjustments, overheads and the audit trail) before seeding. Masters, "
                "users, customers, suppliers and the BOM are preserved."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        demo = bool(options.get("demo")) or options.get("profile") == "demo"
        reset = bool(options.get("reset")) or options.get("profile") == "demo"

        if reset:
            self._reset_transactions()

        units = self._seed_units()
        self._seed_conversions(units)
        users = self._seed_users()
        items = self._seed_items(units)
        self._seed_customers(users)
        self._seed_suppliers()
        self._seed_prices(items, units)

        if apps.is_installed("apps.inventory"):
            from apps.inventory.services import seed_opening_balances

            seed_opening_balances(items=items, units=units, posted_by=users["production"])

        if apps.is_installed("apps.bom"):
            from apps.bom.services import seed_benchmark_bom

            seed_benchmark_bom(items=items, units=units)

        if demo and all(
            apps.is_installed(app)
            for app in ("apps.purchasing", "apps.production", "apps.sales", "apps.payments")
        ):
            self._seed_demo_transactions(users=users, items=items, units=units)

        self.stdout.write(self.style.SUCCESS("Benchmark data seeded successfully."))

    # Documents are deleted child-first so PROTECT foreign keys never block the reset.
    TRANSACTION_MODELS = (
        ("audit", "AuditLog"),
        ("costing", "OverheadEntry"),
        ("payments", "PaymentAllocation"),
        ("payments", "Payment"),
        ("sales", "CreditNote"),
        ("sales", "Dispatch"),
        ("sales", "InvoiceLine"),
        ("sales", "Invoice"),
        ("sales", "OrderLine"),
        ("sales", "Order"),
        ("production", "RunLine"),
        ("production", "ProductionRun"),
        ("purchasing", "PurchaseLine"),
        ("purchasing", "Purchase"),
        ("inventory", "StockAdjustment"),
        ("inventory", "StockLedger"),
    )

    def _reset_transactions(self) -> None:
        """Return every transactional table to empty so demo runs start identically."""
        deleted: list[tuple[str, int]] = []
        for app_label, model_name in self.TRANSACTION_MODELS:
            if not apps.is_installed(f"apps.{app_label}"):
                continue
            model = apps.get_model(app_label, model_name)
            count, _ = model.objects.all().delete()
            if count:
                deleted.append((model_name, count))

        summary = ", ".join(f"{name} {count}" for name, count in deleted) or "nothing"
        self.stdout.write(self.style.WARNING(f"Reset transactional data ({summary})."))

    # Deterministic identifiers so re-running the seed never duplicates documents.
    DEMO_PURCHASE_INVOICE = "KAV-2026-001"
    DEMO_RUN_NOTE = "Seeded demo production run"
    DEMO_ORDER_KEY = UUID("5eed0000-0000-4000-8000-000000000001")
    DEMO_PENDING_ORDER_KEY = UUID("5eed0000-0000-4000-8000-000000000002")

    def _seed_demo_transactions(
        self, *, users: dict[str, User], items: dict[str, Item], units: dict[str, Unit]
    ) -> None:
        """Seed one posted purchase, one posted production run and two sales orders.

        Every screen in the app then has data: purchases, production, invoices,
        dispatch, payments, outstanding dues and the audit trail. All documents
        use fixed identifiers and are guarded by status checks, so running the
        command repeatedly is a no-op.
        """
        from apps.bom.models import BOM
        from apps.payments.services import post_payment
        from apps.production.models import ProductionRun
        from apps.production.services import (
            create_production_run,
            post_production_run,
            update_run_actuals,
        )
        from apps.purchasing.models import Purchase, PurchaseLine
        from apps.purchasing.services import post_purchase
        from apps.sales.models import Order, OrderStatus
        from apps.sales.services import approve_order, post_dispatch, post_invoice, submit_order

        supplier = Supplier.objects.get(code="SUP-KAVERI")
        production_user = users["production"]
        admin_user = users["admin"]

        # 1) Posted supplier purchase — feeds purchases, ledger and WAC screens.
        purchase, created = Purchase.objects.get_or_create(
            invoice_number=self.DEMO_PURCHASE_INVOICE,
            defaults={
                "supplier": supplier,
                "date": date(2026, 4, 2),
                "created_by": production_user,
                "notes": "Seeded demo purchase receipt",
            },
        )
        if created:
            purchase_lines = [
                ("RAW-FLOUR", Decimal("100"), "kg", Decimal("43.1250")),
                ("RAW-OIL", Decimal("25"), "L", Decimal("150.0000")),
                ("RAW-SPICE", Decimal("5"), "kg", Decimal("320.0000")),
                ("PACK-POUCH", Decimal("1000"), "pcs", Decimal("2.2000")),
                ("PACK-CARTON", Decimal("50"), "carton", Decimal("25.0000")),
            ]
            for sku, qty, unit_code, rate in purchase_lines:
                PurchaseLine.objects.create(
                    purchase=purchase,
                    item=items[sku],
                    qty=qty,
                    unit=units[unit_code],
                    unit_rate=rate,
                )
        post_purchase(purchase, production_user)

        # 2) Posted production run — feeds production, variance and ledger screens.
        bom = BOM.objects.filter(product=items["FG-MURUKKU-200G"], is_active=True).first()
        if bom is not None:
            run = ProductionRun.objects.filter(notes=self.DEMO_RUN_NOTE).first()
            if run is None:
                run = create_production_run(
                    bom=bom,
                    user=production_user,
                    batches=1,
                    run_date=date(2026, 4, 3),
                    notes=self.DEMO_RUN_NOTE,
                )
                update_run_actuals(
                    run,
                    actual_output=Decimal("196"),
                    wastage=Decimal("4"),
                    damaged_packaging=Decimal("2"),
                    line_actuals={
                        "RAW-FLOUR": (Decimal("39.5"), units["kg"]),
                        "RAW-OIL": (Decimal("9.8"), units["L"]),
                        "RAW-SPICE": (Decimal("1.2"), units["kg"]),
                        "PACK-POUCH": (Decimal("194"), units["pcs"]),
                        "PACK-CARTON": (Decimal("9"), units["carton"]),
                    },
                )
            post_production_run(run, production_user)

        # 3) Order that runs the full cycle: submitted -> approved -> invoiced
        #    -> dispatched -> partially paid, leaving a visible outstanding balance.
        order = Order.objects.filter(idempotency_key=self.DEMO_ORDER_KEY).first()
        if order is None:
            order = submit_order(
                customer=Customer.objects.get(code="CUST-RET-A"),
                salesman=users["salesmanA"],
                lines=[
                    {
                        "item": items["FG-MURUKKU-200G"],
                        "qty": Decimal("40"),
                        "unit": units["packet"],
                        "unit_price": Decimal("50.00"),
                    }
                ],
                notes="Seeded demo order (Tamil Nadu, intra-state GST)",
                idempotency_key=self.DEMO_ORDER_KEY,
            )
        if order.status == OrderStatus.SUBMITTED:
            approve_order(order, user=admin_user)
            order.refresh_from_db()
        if order.status == OrderStatus.APPROVED:
            invoice = post_invoice(order, user=admin_user)
            post_dispatch(invoice, user=admin_user)
            post_payment(
                customer=order.customer,
                amount=Decimal("1000.00"),
                reference="NEFT-DEMO-0001",
                notes="Seeded demo part payment",
                allocations=[{"invoice_id": invoice.id, "amount": Decimal("1000.00")}],
                user=admin_user,
            )

        # 4) A second order left in `submitted` so approval screens have work to do.
        if not Order.objects.filter(idempotency_key=self.DEMO_PENDING_ORDER_KEY).exists():
            submit_order(
                customer=Customer.objects.get(code="CUST-DIST-B"),
                salesman=users["salesmanB"],
                lines=[
                    {
                        "item": items["FG-MURUKKU-200G"],
                        "qty": Decimal("30"),
                        "unit": units["packet"],
                        "unit_price": Decimal("50.00"),
                    }
                ],
                notes="Seeded demo order awaiting approval (Karnataka, inter-state GST)",
                idempotency_key=self.DEMO_PENDING_ORDER_KEY,
            )

    def _seed_units(self) -> dict[str, Unit]:
        unit_defs = [
            ("g", "Gram"),
            ("kg", "Kilogram"),
            ("ml", "Millilitre"),
            ("L", "Litre"),
            ("pcs", "Pieces"),
            ("packet", "Packet"),
            ("carton", "Carton"),
        ]
        result: dict[str, Unit] = {}
        for code, name in unit_defs:
            unit, _ = Unit.objects.update_or_create(code=code, defaults={"name": name})
            result[code] = unit
        return result

    def _seed_conversions(self, units: dict[str, Unit]) -> None:
        conv_defs = [
            ("kg", "g", Decimal("1000.000000")),
            ("L", "ml", Decimal("1000.000000")),
            ("carton", "packet", Decimal("20.000000")),
        ]
        for from_code, to_code, factor in conv_defs:
            UnitConversion.objects.update_or_create(
                from_unit=units[from_code],
                to_unit=units[to_code],
                defaults={"factor": factor},
            )

    def _seed_users(self) -> dict[str, User]:
        user_defs = [
            ("salesmanA", Role.SALESMAN, "Salesman", "A", False),
            ("salesmanB", Role.SALESMAN, "Salesman", "B", False),
            ("admin", Role.ADMIN, "Admin", "User", True),
            ("production", Role.PRODUCTION, "Production", "Supervisor", False),
            ("auditor", Role.AUDITOR, "Internal", "Auditor", False),
            ("owner", Role.OWNER, "Business", "Owner", False),
        ]
        users: dict[str, User] = {}
        for username, role, first_name, last_name, is_staff in user_defs:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "role": role,
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_staff": is_staff,
                },
            )
            if created:
                user.set_password("benchmark123")
                user.save()
            else:
                changed = False
                if user.role != role:
                    user.role = role
                    changed = True
                if user.is_staff != is_staff:
                    user.is_staff = is_staff
                    changed = True
                if not user.has_usable_password():
                    user.set_password("benchmark123")
                    changed = True
                if changed:
                    user.save()
            users[username] = user
        return users

    def _seed_items(self, units: dict[str, Unit]) -> dict[str, Item]:
        item_defs = [
            (
                "RAW-FLOUR",
                "Rice & Besan Flour Mix",
                ItemType.RAW,
                "g",
                "kg",
                "1102",
                Decimal("5.00"),
            ),
            ("RAW-OIL", "Refined Groundnut Oil", ItemType.RAW, "ml", "L", "1508", Decimal("5.00")),
            ("RAW-SPICE", "Murukku Spice Mix", ItemType.RAW, "g", "kg", "0910", Decimal("5.00")),
            (
                "PACK-POUCH",
                "Printed Pouch 200g",
                ItemType.PACK,
                "pcs",
                "pcs",
                "3923",
                Decimal("18.00"),
            ),
            (
                "PACK-CARTON",
                "Master Carton (20x200g)",
                ItemType.PACK,
                "carton",
                "carton",
                "4819",
                Decimal("18.00"),
            ),
            (
                "FG-MURUKKU-200G",
                "Murukku 200g",
                ItemType.FINISHED,
                "packet",
                "packet",
                "2106",
                Decimal("5.00"),
            ),
        ]
        items: dict[str, Item] = {}
        for sku, name, item_type, base_code, disp_code, hsn, gst_rate in item_defs:
            item, _ = Item.objects.update_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "item_type": item_type,
                    "base_unit": units[base_code],
                    "display_unit": units[disp_code],
                    "hsn": hsn,
                    "gst_rate": gst_rate,
                    "is_active": True,
                },
            )
            items[sku] = item
        return items

    def _seed_customers(self, users: dict[str, User]) -> None:
        Customer.objects.update_or_create(
            code="CUST-RET-A",
            defaults={
                "name": "Retailer A",
                "gstin": "33AABCR1234A1Z5",
                "state": "Tamil Nadu",
                "assigned_salesman": users["salesmanA"],
                "address": "14 Gandhi Bazaar, Salem, Tamil Nadu",
                "phone": "9840011111",
                "is_active": True,
            },
        )
        Customer.objects.update_or_create(
            code="CUST-DIST-B",
            defaults={
                "name": "Distributor B",
                "gstin": "29AABCD5678B1Z2",
                "state": "Karnataka",
                "assigned_salesman": users["salesmanB"],
                "address": "88 Chickpet Main Road, Bengaluru, Karnataka",
                "phone": "9845022222",
                "is_active": True,
            },
        )

    def _seed_suppliers(self) -> None:
        Supplier.objects.update_or_create(
            code="SUP-KAVERI",
            defaults={
                "name": "Kaveri Agro & Packaging Traders",
                "gstin": "33AABCK9999C1Z1",
                "state": "Tamil Nadu",
                "address": "22 Rice Mill Road, Erode, Tamil Nadu",
                "phone": "9842233333",
                "is_active": True,
            },
        )

    def _seed_prices(self, items: dict[str, Item], units: dict[str, Unit]) -> None:
        PriceList.objects.update_or_create(
            item=items["FG-MURUKKU-200G"],
            customer=None,
            unit=units["packet"],
            effective_from=date(2026, 4, 1),
            defaults={
                "rate": Decimal("50.00"),
                "is_active": True,
            },
        )
