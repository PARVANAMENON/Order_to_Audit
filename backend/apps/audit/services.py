"""Audit service — log_action utility used by other services."""
from __future__ import annotations

import json

from apps.accounts.models import User
from apps.audit.models import AuditLog


def log_action(
    *,
    user: User | None,
    model_name: str,
    object_id: int,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    notes: str = "",
) -> AuditLog:
    """Write one immutable audit-log row.

    Args:
        user: The actor (may be None for system actions).
        model_name: Django model label, e.g. "Order", "Invoice".
        object_id: Primary key of the affected object.
        action: Short verb phrase, e.g. "approve_order", "post_invoice".
        before: State snapshot before the change (serialisable dict).
        after: State snapshot after the change.
        notes: Optional free-text annotation.
    """
    return AuditLog.objects.create(
        user=user,
        model_name=model_name,
        object_id=object_id,
        action=action,
        before_json=json.dumps(before or {}, default=str),
        after_json=json.dumps(after or {}, default=str),
        notes=notes,
    )
