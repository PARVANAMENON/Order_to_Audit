"""Admin registration for production."""

from django.contrib import admin

from apps.production.models import ProductionRun, RunLine


class RunLineInline(admin.TabularInline):
    model = RunLine
    extra = 0


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):
    list_display = (
        "run_number",
        "bom",
        "run_date",
        "expected_output",
        "actual_output",
        "yield_variance_pct",
        "yield_flagged",
        "status",
    )
    inlines = [RunLineInline]
