"""Costing views."""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.costing.models import OverheadType
from apps.costing.services import cost_per_packet, post_overhead
from apps.production.models import ProductionRun

VIEW_ROLES = (Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)
WRITE_ROLES = (Role.ADMIN, Role.PRODUCTION)


@role_required(*VIEW_ROLES)
def run_costing_view(request: HttpRequest, pk: int) -> HttpResponse:
    run = get_object_or_404(
        ProductionRun.objects.select_related("bom", "bom__product"), pk=pk
    )
    overheads = run.overheads.all()
    breakdown = cost_per_packet(run)
    overhead_types = OverheadType.choices

    if request.method == "POST" and (
        request.user.is_superuser or request.user.role in WRITE_ROLES
    ):
        try:
            post_overhead(
                run=run,
                overhead_type=request.POST.get("overhead_type", ""),
                amount=request.POST.get("amount", "0"),
                description=request.POST.get("description", ""),
                user=request.user,
            )
            messages.success(request, "Overhead entry added.")
            return redirect("costing:run-costing", pk=pk)
        except (ValidationError, ValueError) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "costing/run_costing.html",
        {
            "run": run,
            "overheads": overheads,
            "breakdown": breakdown,
            "overhead_types": overhead_types,
        },
    )
