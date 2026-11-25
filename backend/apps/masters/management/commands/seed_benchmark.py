"""Idempotent seed command for benchmark master data and test logins."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

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

    @transaction.atomic
    def handle(self, *args, **options) -> None:
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

        self.stdout.write(self.style.SUCCESS("Benchmark data seeded successfully."))

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
