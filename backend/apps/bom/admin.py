"""Admin registration for bom."""

from django.contrib import admin

from apps.bom.models import BOM, BOMLine


class BOMLineInline(admin.TabularInline):
    model = BOMLine
    extra = 1


@admin.register(BOM)
class BOMAdmin(admin.ModelAdmin):
    list_display = ("name", "product", "expected_yield", "is_active")
    inlines = [BOMLineInline]
