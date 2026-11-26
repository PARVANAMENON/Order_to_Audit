"""Payments admin."""
from django.contrib import admin

from apps.payments.models import Payment, PaymentAllocation


class AllocInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "amount", "payment_date")
    inlines = [AllocInline]
