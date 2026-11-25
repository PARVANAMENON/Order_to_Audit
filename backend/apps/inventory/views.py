"""Views for inventory summary, ledger, and manual adjustments."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.inventory.models import SourceType, StockAdjustment, StockLedger
from apps.inventory.services import (
    balance,
    balance_in_unit,
    get_wac,
    get_wac_in_unit,
    post_adjustment,
)
from apps.masters.models import Item, Unit
from apps.masters.services import UnitConversionError

VIEW_ROLES = (Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)
WRITE_ROLES = (Role.ADMIN, Role.PRODUCTION)


@role_required(*VIEW_ROLES)
def stock_summary_view(request: HttpRequest) -> HttpResponse:
    """Display ledger-derived stock balance and WAC for every active item."""
    rows = []
    for item in Item.objects.select_related("base_unit", "display_unit").filter(is_active=True):
        base_bal = balance(item)
        disp_unit = item.preferred_display_unit
        disp_bal = balance_in_unit(item, disp_unit)
        base_wac = get_wac(item)
        disp_wac = get_wac_in_unit(item, disp_unit)
        stock_value = (base_bal * base_wac).quantize(Decimal("0.01"))
        rows.append(
            {
                "item": item,
                "base_balance": base_bal,
                "display_unit": disp_unit,
                "display_balance": disp_bal,
                "base_wac": base_wac,
                "display_wac": disp_wac,
                "stock_value": stock_value,
            }
        )
    return render(request, "inventory/summary.html", {"rows": rows})


@role_required(*VIEW_ROLES)
def stock_ledger_view(request: HttpRequest) -> HttpResponse:
    """Display StockLedger movements with optional filters and source document links."""
    entries = StockLedger.objects.select_related("item", "item__base_unit", "user").all()
    item_id = request.GET.get("item")
    source_type = request.GET.get("source_type")
    source_id = request.GET.get("source_id")
    if item_id:
        entries = entries.filter(item_id=item_id)
    if source_type:
        entries = entries.filter(source_type=source_type)
    if source_id:
        entries = entries.filter(source_id=source_id)

    return render(
        request,
        "inventory/ledger.html",
        {
            "entries": entries[:200],
            "items": Item.objects.filter(is_active=True),
            "source_types": SourceType.choices,
            "selected_item": item_id or "",
            "selected_source_type": source_type or "",
        },
    )


@role_required(*WRITE_ROLES)
def stock_adjust_view(request: HttpRequest) -> HttpResponse:
    """Create and post a manual stock adjustment with a mandatory reason."""
    items = Item.objects.select_related("base_unit", "display_unit").filter(is_active=True)
    units = Unit.objects.all()

    if request.method == "POST":
        item = get_object_or_404(Item, pk=request.POST.get("item_id"))
        unit = get_object_or_404(Unit, pk=request.POST.get("unit_id"))
        qty_raw = request.POST.get("qty", "").strip()
        rate_raw = request.POST.get("unit_rate", "").strip()
        reason = request.POST.get("reason", "")
        try:
            adj = post_adjustment(
                item=item,
                qty=qty_raw,
                unit=unit,
                reason=reason,
                user=request.user,
                unit_rate=rate_raw or None,
            )
            messages.success(request, f"Posted adjustment ADJ-{adj.id} for {item.sku}.")
            return redirect("inventory:adjustment-detail", pk=adj.id)
        except (ValidationError, UnitConversionError, ValueError, ArithmeticError) as exc:
            messages.error(request, str(exc))

    recent = StockAdjustment.objects.select_related("item", "input_unit", "adjusted_by").all()[:20]
    return render(
        request,
        "inventory/adjust.html",
        {"items": items, "units": units, "recent_adjustments": recent},
    )


@role_required(*VIEW_ROLES)
def adjustment_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View details of a posted StockAdjustment."""
    adj = get_object_or_404(
        StockAdjustment.objects.select_related(
            "item", "item__base_unit", "input_unit", "adjusted_by"
        ),
        pk=pk,
    )
    ledger_rows = StockLedger.objects.filter(
        source_type=SourceType.ADJUSTMENT, source_id=adj.id
    ).select_related("item", "user")
    return render(
        request,
        "inventory/adjustment_detail.html",
        {"adjustment": adj, "ledger_rows": ledger_rows},
    )
