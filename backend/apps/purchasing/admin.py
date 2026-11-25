"""Admin registration for purchasing."""

from django.contrib import admin

from apps.purchasing.models import Purchase, PurchaseLine


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 1


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("id", "invoice_number", "supplier", "date", "status")
    inlines = [PurchaseLineInline]
