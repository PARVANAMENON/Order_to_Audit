"""Payment views."""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.masters.models import Customer
from apps.payments.models import Payment
from apps.payments.services import ageing_buckets, customer_outstanding, post_payment

VIEW_ROLES = (Role.ADMIN, Role.AUDITOR, Role.OWNER)
WRITE_ROLES = (Role.ADMIN,)


@role_required(*VIEW_ROLES)
def payment_list_view(request: HttpRequest) -> HttpResponse:
    customers = Customer.objects.filter(is_active=True)
    rows = []
    for c in customers:
        outstanding = customer_outstanding(c)
        if outstanding > 0:
            buckets = ageing_buckets(c)
            rows.append({"customer": c, "outstanding": outstanding, "buckets": buckets})
    return render(request, "payments/outstanding.html", {"rows": rows})


@role_required(*WRITE_ROLES)
def payment_create_view(request: HttpRequest) -> HttpResponse:
    customers = Customer.objects.filter(is_active=True)
    if request.method == "POST":
        cust = get_object_or_404(Customer, pk=request.POST.get("customer_id"))
        amt = request.POST.get("amount", "0")
        ref = request.POST.get("reference", "")
        notes = request.POST.get("notes", "")
        try:
            pay = post_payment(
                customer=cust,
                amount=amt,
                reference=ref,
                notes=notes,
                user=request.user,
            )
            messages.success(request, f"Payment PAY-{pay.id} of Rs {pay.amount} recorded.")
            return redirect("payments:list")
        except (ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
    return render(request, "payments/create.html", {
        "customers": customers,
        "today": timezone.localdate().isoformat(),
    })


@role_required(*VIEW_ROLES)
def payment_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    pay = get_object_or_404(
        Payment.objects.select_related("customer", "received_by"), pk=pk
    )
    allocs = pay.allocations.select_related("invoice").all()
    return render(request, "payments/detail.html", {"payment": pay, "allocations": allocs})
