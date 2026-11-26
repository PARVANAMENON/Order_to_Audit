"""Payment and PaymentAllocation models."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import Customer
from apps.sales.models import Invoice


class Payment(models.Model):
    """Customer payment receipt."""

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_payments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-id"]

    def __str__(self) -> str:
        return f"PAY-{self.id} {self.customer.name} Rs{self.amount}"


class PaymentAllocation(models.Model):
    """Allocation of a payment to a specific invoice."""

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payment_allocations"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    allocated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["allocated_at"]

    def __str__(self) -> str:
        return f"PAY-{self.payment_id} -> {self.invoice.fy_number} Rs{self.amount}"
