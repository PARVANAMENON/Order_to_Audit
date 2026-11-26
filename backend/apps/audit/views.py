"""Audit log views — read-only for all non-salesman roles."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.audit.models import AuditLog

VIEW_ROLES = (Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)


@role_required(*VIEW_ROLES)
def audit_log_view(request: HttpRequest) -> HttpResponse:
    """Display recent audit log entries with optional filters."""
    logs = AuditLog.objects.select_related("user").order_by("-timestamp")
    model_filter = request.GET.get("model", "")
    action_filter = request.GET.get("action", "")
    if model_filter:
        logs = logs.filter(model_name__icontains=model_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    logs = logs[:200]
    return render(request, "audit/log.html", {"logs": logs})
