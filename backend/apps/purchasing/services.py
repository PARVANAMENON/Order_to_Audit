"""Transactional purchase posting services."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.inventory.models import SourceType, StockLedger
from apps.masters.models import Item
from apps.masters.services import convert_quantity, convert_rate
from apps.purchasing.models import Purchase, PurchaseStatus


@transaction.atomic
def post_purchase(purchase: Purchase, user: User) -> Purchase:
    """Post a draft Purchase to StockLedger atomically and idempotently.

    Converts each line quantity and unit rate into the item's base unit via
    UnitConversion, writes positive StockLedger receipt rows, and marks the
    purchase as posted. Repeated calls on an already-posted purchase are no-ops.
    """
    locked_purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
    if locked_purchase.status == PurchaseStatus.POSTED:
        return locked_purchase

    lines = list(locked_purchase.lines.select_related("item", "item__base_unit", "unit").all())
    if not lines:
        raise ValidationError("Cannot post a purchase without line items.")

    item_ids = sorted({line.item_id for line in lines})
    locked_items = {
        it.pk: it for it in Item.objects.select_for_update().filter(id__in=item_ids).order_by("id")
    }

    movement_dt = timezone.make_aware(
        datetime.combine(locked_purchase.date, time(12, 0)),
        timezone.get_current_timezone(),
    )

    for line in lines:
        if line.qty <= Decimal("0"):
            raise ValidationError(f"Purchase line for {line.item.sku} must have positive qty.")
        if line.unit_rate < Decimal("0"):
            raise ValidationError(f"Purchase line for {line.item.sku} cannot have negative rate.")

        item = locked_items[line.item_id]
        base_qty = convert_quantity(line.qty, line.unit, item.base_unit)
        base_rate = convert_rate(line.unit_rate, line.unit, item.base_unit)

        StockLedger.objects.create(
            item=item,
            date=movement_dt,
            qty=base_qty,
            unit_rate=base_rate,
            source_type=SourceType.PURCHASE,
            source_id=locked_purchase.id,
            source_ref=f"PUR-{locked_purchase.id}",
            user=user,
            batch=line.batch,
            expiry=line.expiry,
            notes=f"Supplier invoice {locked_purchase.invoice_number}",
        )

    locked_purchase.status = PurchaseStatus.POSTED
    locked_purchase.posted_by = user
    locked_purchase.posted_at = timezone.now()
    locked_purchase.save(update_fields=["status", "posted_by", "posted_at"])
    return locked_purchase
