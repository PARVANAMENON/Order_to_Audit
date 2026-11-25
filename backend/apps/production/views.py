"""Production supervisor views for creating runs, entering actuals, and inspecting variances."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.bom.models import BOM
from apps.inventory.models import SourceType, StockLedger
from apps.masters.models import Unit
from apps.masters.services import UnitConversionError
from apps.production.models import ProductionRun, ProductionRunStatus
from apps.production.services import (
    create_production_run,
    post_production_run,
    update_run_actuals,
)

VIEW_ROLES = (Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)
WRITE_ROLES = (Role.ADMIN, Role.PRODUCTION)


@role_required(*VIEW_ROLES)
def production_list_view(request: HttpRequest) -> HttpResponse:
    """List all production runs with yield variance and flag indicators."""
    runs = ProductionRun.objects.select_related("bom", "bom__product", "created_by", "posted_by")
    return render(request, "production/list.html", {"runs": runs})


@role_required(*WRITE_ROLES)
def production_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new draft production run from an active BOM."""
    boms = BOM.objects.select_related("product").filter(is_active=True)

    if request.method == "POST":
        bom = get_object_or_404(BOM, pk=request.POST.get("bom_id"))
        batches_raw = request.POST.get("batches", "1").strip()
        date_str = request.POST.get("run_date", "").strip()
        notes = request.POST.get("notes", "").strip()
        try:
            parsed_date = (
                timezone.datetime.fromisoformat(date_str).date()
                if date_str
                else timezone.localdate()
            )
            run = create_production_run(
                bom=bom,
                batches=batches_raw,
                run_date=parsed_date,
                user=request.user,
                notes=notes,
            )
            messages.success(request, f"Created production run {run.run_number}.")
            return redirect("production:detail", pk=run.id)
        except (
            ValidationError,
            UnitConversionError,
            ValueError,
            TypeError,
            ArithmeticError,
        ) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "production/create.html",
        {"boms": boms, "today": timezone.localdate().isoformat()},
    )


@role_required(*VIEW_ROLES)
def production_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View planned vs actual consumption, highlighted variance flags, and ledger rows."""
    run = get_object_or_404(
        ProductionRun.objects.select_related(
            "bom", "bom__product", "bom__product__base_unit", "created_by", "posted_by"
        ),
        pk=pk,
    )
    lines = run.lines.select_related("item", "item__base_unit", "unit").all()
    units = Unit.objects.all()
    ledger_rows = StockLedger.objects.filter(
        source_id=run.id,
        source_type__in=[
            SourceType.PRODUCTION_ISSUE,
            SourceType.PRODUCTION_RECEIPT,
            SourceType.PRODUCTION_REVERSAL,
        ],
    ).select_related("item", "item__base_unit", "user")
    can_edit = request.user.is_superuser or request.user.role in WRITE_ROLES
    return render(
        request,
        "production/detail.html",
        {
            "run": run,
            "lines": lines,
            "units": units,
            "ledger_rows": ledger_rows,
            "can_edit": can_edit,
        },
    )


@role_required(*WRITE_ROLES)
def production_save_and_post_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Save actuals on a production run and optionally post/re-post to StockLedger."""
    if request.method != "POST":
        return redirect("production:detail", pk=pk)

    run = get_object_or_404(ProductionRun, pk=pk)
    action = request.POST.get("action", "save")
    was_posted = run.status == ProductionRunStatus.POSTED

    try:
        line_actuals: dict[int, tuple[str, Unit]] = {}
        for line in run.lines.all():
            qty_raw = request.POST.get(f"actual_qty_{line.id}", "").strip()
            unit_id = request.POST.get(f"unit_{line.id}")
            if qty_raw != "" and unit_id:
                unit = get_object_or_404(Unit, pk=unit_id)
                line_actuals[line.id] = (qty_raw, unit)

        update_run_actuals(
            run,
            actual_output=request.POST.get("actual_output", "0").strip(),
            wastage=request.POST.get("wastage", "0").strip() or "0",
            damaged_packaging=request.POST.get("damaged_packaging", "0").strip() or "0",
            line_actuals=line_actuals,
            notes=request.POST.get("notes", run.notes),
        )

        if action == "post":
            post_production_run(run, request.user, repost=was_posted)
            verb = "Re-posted" if was_posted else "Posted"
            messages.success(request, f"{verb} {run.run_number} to StockLedger.")
        else:
            messages.success(request, f"Saved actuals for {run.run_number}.")
    except (ValidationError, UnitConversionError, ValueError, TypeError, ArithmeticError) as exc:
        messages.error(request, str(exc))

    return redirect("production:detail", pk=run.id)
