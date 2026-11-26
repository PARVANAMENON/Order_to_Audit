"""AuditLog model — records every significant write action for auditability."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Immutable audit trail entry for any significant state change."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    model_name = models.CharField(max_length=64, db_index=True)
    object_id = models.PositiveBigIntegerField(db_index=True)
    action = models.CharField(max_length=32)  # e.g. "approve_order", "post_invoice"
    before_json = models.TextField(blank=True)
    after_json = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.action} on {self.model_name}#{self.object_id} by {self.user_id}"
