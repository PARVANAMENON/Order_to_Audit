"""Audit log admin."""
from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "model_name", "object_id", "user")
    list_filter = ("action", "model_name")
    search_fields = ("model_name", "action", "notes")
    readonly_fields = (
        "timestamp",
        "user",
        "model_name",
        "object_id",
        "action",
        "before_json",
        "after_json",
        "notes",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
