"""Reports views: sales register, GST summary, purchase register, variance, stock, dues."""
from __future__ import annotations

import csv
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.inventory.models import StockLedger
from apps.inventory.services import balance
from apps.masters.models import Item
from apps.payments.services import customer_outstanding
from apps.production.models import ProductionRun, ProductionRunStatus
from apps.purchasing.models import Purchase
from apps.sales.models import Invoice, InvoiceStatus

VIEW_ROLES = (Role.ADMIN, Role.AUDITOR, Role.OWNER)


def _parse_dates(request: HttpRequest) -> tuple[date, date]:
    today = timezone.localdate()
    try:
        default_from = (today - timedelta(days=30)).isoformat()
        date_from = date.fromisoformat(request.GET.get("date_from", default_from))
    except ValueError:
        date_from = today - timedelta(days=30)
    try:
        date_to = date.fromisoformat(request.GET.get("date_to", today.isoformat()))
    except ValueError:
        date_to = today
    return date_from, date_to


@role_required(*VIEW_ROLES)
def sales_register_view(request: HttpRequest) -> HttpResponse:
    """Sales register: list all invoices in date range with line totals."""
    date_from, date_to = _parse_dates(request)
    invoices = (
        Invoice.objects.filter(invoice_date__gte=date_from, invoice_date__lte=date_to)
        .select_related("customer", "order__salesman")
        .prefetch_related("lines")
        .order_by("invoice_date", "id")
    )
    total_taxable = sum(i.taxable_value for i in invoices)
    total_cgst = sum(i.cgst for i in invoices)
    total_sgst = sum(i.sgst for i in invoices)
    total_igst = sum(i.igst for i in invoices)
    total_amount = sum(i.total_amount for i in invoices)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="sales_register.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["Invoice No", "Date", "Customer", "Taxable", "CGST", "SGST", "IGST", "Total", "Status"]
        )
        for inv in invoices:
            writer.writerow([
                inv.fy_number, inv.invoice_date, inv.customer.name,
                inv.taxable_value, inv.cgst, inv.sgst, inv.igst, inv.total_amount, inv.status
            ])
        return response

    return render(request, "reports/sales_register.html", {
        "invoices": invoices,
        "date_from": date_from,
        "date_to": date_to,
        "total_taxable": total_taxable,
        "total_cgst": total_cgst,
        "total_sgst": total_sgst,
        "total_igst": total_igst,
        "total_amount": total_amount,
    })


@role_required(*VIEW_ROLES)
def gst_summary_view(request: HttpRequest) -> HttpResponse:
    """GST summary: aggregate CGST, SGST, IGST for the period."""
    date_from, date_to = _parse_dates(request)
    invoices = Invoice.objects.filter(
        invoice_date__gte=date_from, invoice_date__lte=date_to, status=InvoiceStatus.ACTIVE
    )
    summary = invoices.aggregate(
        taxable=Sum("taxable_value"),
        cgst=Sum("cgst"),
        sgst=Sum("sgst"),
        igst=Sum("igst"),
        total=Sum("total_amount"),
    )
    # Coerce None to 0
    for k in summary:
        summary[k] = summary[k] or Decimal("0.00")
    return render(request, "reports/gst_summary.html", {
        "summary": summary,
        "date_from": date_from,
        "date_to": date_to,
    })


@role_required(*VIEW_ROLES)
def purchase_register_view(request: HttpRequest) -> HttpResponse:
    """Purchase register: all purchases in date range."""
    date_from, date_to = _parse_dates(request)
    purchases = (
        Purchase.objects.filter(date__gte=date_from, date__lte=date_to)
        .select_related("supplier", "created_by")
        .prefetch_related("lines__item")
        .order_by("date", "id")
    )
    total = sum(p.total_amount for p in purchases)
    return render(request, "reports/purchase_register.html", {
        "purchases": purchases,
        "date_from": date_from,
        "date_to": date_to,
        "total": total,
    })


@role_required(*VIEW_ROLES)
def production_variance_report_view(request: HttpRequest) -> HttpResponse:
    """Production variance report: show flagged runs in date range."""
    date_from, date_to = _parse_dates(request)
    runs = (
        ProductionRun.objects.filter(
            run_date__gte=date_from, run_date__lte=date_to
        )
        .select_related("bom__product", "created_by")
        .prefetch_related("run_lines")
        .order_by("run_date", "id")
    )
    return render(request, "reports/production_variance.html", {
        "runs": runs,
        "date_from": date_from,
        "date_to": date_to,
    })


@role_required(*VIEW_ROLES)
def stock_ledger_report_view(request: HttpRequest) -> HttpResponse:
    """Stock ledger report: movements for a specific item in date range."""
    date_from, date_to = _parse_dates(request)
    items = Item.objects.filter(is_active=True).order_by("sku")
    item_id = request.GET.get("item_id")
    ledger = []
    selected_item = None
    if item_id:
        selected_item = items.filter(pk=item_id).first()
        if selected_item:
            ledger = (
                StockLedger.objects.filter(
                    item=selected_item, date__date__gte=date_from, date__date__lte=date_to
                )
                .select_related("user", "item")
                .order_by("date", "id")
            )
    return render(request, "reports/stock_ledger.html", {
        "items": items,
        "ledger": ledger,
        "selected_item": selected_item,
        "date_from": date_from,
        "date_to": date_to,
    })


@role_required(*VIEW_ROLES)
def outstanding_report_view(request: HttpRequest) -> HttpResponse:
    """Outstanding dues report per customer."""
    from apps.masters.models import Customer
    customers = Customer.objects.filter(is_active=True).order_by("name")
    rows = []
    for c in customers:
        outstanding = customer_outstanding(c)
        if outstanding > 0:
            rows.append({"customer": c, "outstanding": outstanding})
    total = sum(r["outstanding"] for r in rows)
    return render(request, "reports/outstanding.html", {
        "rows": rows,
        "total": total,
    })


@role_required(Role.ADMIN, Role.OWNER, Role.PRODUCTION, Role.AUDITOR, Role.SALESMAN)
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """Owner/admin dashboard: today's orders, low stock, flagged runs, dues."""
    today = timezone.localdate()
    from apps.masters.models import Customer
    from apps.sales.models import Order, OrderStatus

    todays_orders = Order.objects.filter(order_date=today).count()
    pending_orders = Order.objects.filter(status=OrderStatus.SUBMITTED).count()
    flagged_runs = (
        ProductionRun.objects.filter(status=ProductionRunStatus.POSTED, lines__flagged=True)
        .distinct()
        .count()
    )
    low_stock_items = []
    for item in Item.objects.filter(is_active=True, item_type="raw"):
        bal = balance(item)
        if bal < Decimal("10"):
            low_stock_items.append({"item": item, "balance": bal})
    total_outstanding = sum(
        customer_outstanding(c) for c in Customer.objects.filter(is_active=True)
    )
    return render(request, "reports/dashboard.html", {
        "todays_orders": todays_orders,
        "pending_orders": pending_orders,
        "flagged_runs": flagged_runs,
        "low_stock_items": low_stock_items,
        "total_outstanding": total_outstanding,
        "today": today,
    })
