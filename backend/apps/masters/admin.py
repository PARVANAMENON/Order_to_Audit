"""Admin configuration for masters models."""

from django.contrib import admin

from apps.masters.models import Customer, Item, PriceList, Supplier, Unit, UnitConversion

admin.site.register(Unit)
admin.site.register(UnitConversion)
admin.site.register(Item)
admin.site.register(Customer)
admin.site.register(Supplier)
admin.site.register(PriceList)
