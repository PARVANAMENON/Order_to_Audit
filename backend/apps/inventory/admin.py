"""Admin configuration for inventory."""

from django.contrib import admin

from apps.inventory.models import StockAdjustment, StockLedger

admin.site.register(StockLedger)
admin.site.register(StockAdjustment)
