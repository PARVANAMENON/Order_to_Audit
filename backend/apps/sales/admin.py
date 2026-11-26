"""Admin registration for sales."""
from django.contrib import admin

from apps.sales.models import CreditNote, Dispatch, Invoice, InvoiceLine, Order, OrderLine


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "salesman", "status", "order_date")
    inlines = [OrderLineInline]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("fy_number", "customer", "total_amount", "status", "invoice_date")
    inlines = [InvoiceLineInline]


admin.site.register(Dispatch)
admin.site.register(CreditNote)
