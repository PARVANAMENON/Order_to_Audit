"""Domain services for masters, primarily table-driven unit conversions."""

from __future__ import annotations

from collections import deque
from decimal import ROUND_HALF_UP, Decimal

from apps.masters.models import Customer, Item, PriceList, Unit, UnitConversion

QTY_QUANT = Decimal("0.001")
RATE_QUANT = Decimal("0.000001")


class UnitConversionError(ValueError):
    """Raised when two units cannot be converted using UnitConversion rules."""


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed for quantities or money; pass Decimal or str.")
    return Decimal(str(value))


def get_conversion_factor(from_unit: Unit, to_unit: Unit) -> Decimal:
    """Return exact Decimal factor f such that 1 from_unit = f * to_unit."""
    if from_unit.pk == to_unit.pk:
        return Decimal("1")

    adjacency: dict[int, list[tuple[int, Decimal]]] = {}
    for conv in UnitConversion.objects.all():
        if conv.factor <= 0:
            continue
        adjacency.setdefault(conv.from_unit_id, []).append((conv.to_unit_id, conv.factor))
        adjacency.setdefault(conv.to_unit_id, []).append(
            (conv.from_unit_id, Decimal("1") / conv.factor)
        )

    queue: deque[tuple[int, Decimal]] = deque([(from_unit.pk, Decimal("1"))])
    visited: set[int] = {from_unit.pk}

    while queue:
        current_id, acc_factor = queue.popleft()
        for neighbor_id, edge_factor in adjacency.get(current_id, ()):
            if neighbor_id in visited:
                continue
            next_factor = acc_factor * edge_factor
            if neighbor_id == to_unit.pk:
                return next_factor
            visited.add(neighbor_id)
            queue.append((neighbor_id, next_factor))

    raise UnitConversionError(
        f"No unit conversion defined between '{from_unit.code}' and '{to_unit.code}'."
    )


def convert_quantity(
    qty: Decimal | int | str,
    from_unit: Unit,
    to_unit: Unit,
    quant: Decimal = QTY_QUANT,
) -> Decimal:
    """Convert qty from `from_unit` to `to_unit` using the UnitConversion table."""
    dec_qty = _to_decimal(qty)
    factor = get_conversion_factor(from_unit, to_unit)
    return (dec_qty * factor).quantize(quant, rounding=ROUND_HALF_UP)


def convert_rate(
    rate_per_from_unit: Decimal | int | str,
    from_unit: Unit,
    to_unit: Unit,
    quant: Decimal = RATE_QUANT,
) -> Decimal:
    """Convert unit rate from per-`from_unit` to per-`to_unit`."""
    dec_rate = _to_decimal(rate_per_from_unit)
    factor = get_conversion_factor(from_unit, to_unit)
    return (dec_rate / factor).quantize(quant, rounding=ROUND_HALF_UP)


def get_effective_price(item: Item, customer: Customer | None = None) -> PriceList | None:
    """Return latest active customer-specific price or fallback default price."""
    if customer is not None:
        cust_price = (
            PriceList.objects.filter(item=item, customer=customer, is_active=True)
            .order_by("-effective_from")
            .first()
        )
        if cust_price is not None:
            return cust_price
    return (
        PriceList.objects.filter(item=item, customer__isnull=True, is_active=True)
        .order_by("-effective_from")
        .first()
    )
