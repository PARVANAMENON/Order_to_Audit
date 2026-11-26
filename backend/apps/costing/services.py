"""Cost-per-packet and margin computation services."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.accounts.models import User
from apps.audit.services import log_action
from apps.costing.models import OverheadEntry, OverheadType
from apps.production.models import ProductionRun

MONEY = Decimal("0.01")


@transaction.atomic
def post_overhead(
    *,
    run: ProductionRun,
    overhead_type: str,
    amount: Decimal | str,
    user: User,
    description: str = "",
) -> OverheadEntry:
    """Record an overhead entry against a production run and audit it."""
    if overhead_type not in OverheadType.values:
        raise ValidationError("Invalid overhead type.")
    dec_amount = Decimal(str(amount)).quantize(MONEY, rounding=ROUND_HALF_UP)
    if dec_amount <= 0:
        raise ValidationError("Overhead amount must be positive.")
    entry = OverheadEntry.objects.create(
        run=run,
        overhead_type=overhead_type,
        amount=dec_amount,
        description=description.strip(),
        entered_by=user,
    )
    log_action(
        user=user,
        model_name="OverheadEntry",
        object_id=entry.id,
        action="post_overhead",
        after={
            "run": run.run_number,
            "overhead_type": overhead_type,
            "amount": str(dec_amount),
        },
        notes=description.strip(),
    )
    return entry


def run_overhead_total(run: ProductionRun) -> Decimal:
    """Return total overhead entered against this production run."""
    total = run.overheads.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    return Decimal(str(total)).quantize(MONEY, rounding=ROUND_HALF_UP)


def cost_per_packet(run: ProductionRun) -> dict[str, Decimal]:
    """Compute full cost breakdown and margin for a production run.

    Returns dict with material_cost, overhead, total_cost, good_packets,
    cost_per_packet, selling_price, margin, margin_pct.
    """
    material = run.material_cost
    overhead = run_overhead_total(run)
    total = (material + overhead).quantize(MONEY, rounding=ROUND_HALF_UP)
    packets = run.actual_output  # in product's base unit (packets)

    if packets and packets > 0:
        cpp = (total / packets).quantize(MONEY, rounding=ROUND_HALF_UP)
    else:
        cpp = Decimal("0.00")

    # Try to get default selling price for the product
    from apps.masters.models import PriceList
    price_obj = (
        PriceList.objects.filter(item=run.bom.product, customer__isnull=True, is_active=True)
        .order_by("-effective_from")
        .first()
    )
    # Convert price to base-unit price if needed
    if price_obj:
        from apps.masters.services import convert_rate
        selling = convert_rate(price_obj.rate, price_obj.unit, run.bom.product.base_unit)
    else:
        selling = Decimal("0.00")

    margin = (selling - cpp).quantize(MONEY, rounding=ROUND_HALF_UP)
    margin_pct = (
        (margin / selling * Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
        if selling > 0
        else Decimal("0.00")
    )

    return {
        "material_cost": material,
        "overhead": overhead,
        "total_cost": total,
        "good_packets": packets,
        "cost_per_packet": cpp,
        "selling_price": selling,
        "margin": margin,
        "margin_pct": margin_pct,
    }
