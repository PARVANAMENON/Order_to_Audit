"""Login, logout, and role-based landing views."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.models import Role


class CustomLoginView(LoginView):
    """Simple session login page."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class CustomLogoutView(LogoutView):
    """Session logout view."""

    next_page = "/login/"


@login_required
def landing_view(request: HttpRequest) -> HttpResponse:
    """Role-based landing page showing permitted workflows."""
    user = request.user
    role = getattr(user, "role", Role.SALESMAN)

    role_cards: dict[str, list[dict[str, str]]] = {
        Role.SALESMAN: [
            {
                "title": "Master Catalog",
                "desc": "View active items and price list.",
                "url": "/masters/items/",
            },
            {
                "title": "Customers",
                "desc": "View assigned customers and GST details.",
                "url": "/masters/customers/",
            },
            {
                "title": "My Orders",
                "desc": "Place orders and track approval status.",
                "url": "/sales/orders/",
            },
            {
                "title": "Invoices",
                "desc": "View invoices raised against your orders.",
                "url": "/sales/invoices/",
            },
        ],
        Role.ADMIN: [
            {
                "title": "Stock Summary",
                "desc": "Real-time ledger balances & WAC.",
                "url": "/inventory/",
            },
            {
                "title": "Purchases",
                "desc": "Record supplier receipts & post to ledger.",
                "url": "/purchasing/",
            },
            {
                "title": "Production Runs",
                "desc": "Review BOM runs and variances.",
                "url": "/production/",
            },
            {
                "title": "Master Data",
                "desc": "Items, unit conversions, customers, prices.",
                "url": "/masters/items/",
            },
            {
                "title": "Sales Orders",
                "desc": "Approve or reject submitted orders.",
                "url": "/sales/orders/",
            },
            {
                "title": "Invoices & Dispatch",
                "desc": "Raise GST invoices, dispatch, credit notes.",
                "url": "/sales/invoices/",
            },
            {
                "title": "Payments",
                "desc": "Record receipts and review outstanding ageing.",
                "url": "/payments/",
            },
            {
                "title": "Reports",
                "desc": "Sales register, GST, purchase & variance reports.",
                "url": "/reports/",
            },
            {
                "title": "Audit Log",
                "desc": "Review every significant write action.",
                "url": "/audit/",
            },
        ],
        Role.PRODUCTION: [
            {
                "title": "Production Runs",
                "desc": "Create runs, enter actuals, check flags.",
                "url": "/production/",
            },
            {
                "title": "Purchase Receipts",
                "desc": "Enter & post raw/pack material receipts.",
                "url": "/purchasing/",
            },
            {
                "title": "Stock Summary",
                "desc": "Current raw, packaging & FG stock.",
                "url": "/inventory/",
            },
            {
                "title": "Stock Adjustments",
                "desc": "Post manual adjustments with reason.",
                "url": "/inventory/adjust/",
            },
            {
                "title": "Production Reports",
                "desc": "Yield and variance reporting.",
                "url": "/reports/production/",
            },
            {
                "title": "Audit Log",
                "desc": "Review recorded write actions.",
                "url": "/audit/",
            },
        ],
        Role.AUDITOR: [
            {
                "title": "Stock Ledger (Read-Only)",
                "desc": "Inspect every movement & source doc.",
                "url": "/inventory/ledger/",
            },
            {
                "title": "Stock Summary (Read-Only)",
                "desc": "Verify closing balances & WAC.",
                "url": "/inventory/",
            },
            {
                "title": "Production Runs (Read-Only)",
                "desc": "Inspect planned vs actual variances.",
                "url": "/production/",
            },
            {
                "title": "Master Data (Read-Only)",
                "desc": "Verify units, items, GST & prices.",
                "url": "/masters/items/",
            },
            {
                "title": "Sales Register (Read-Only)",
                "desc": "Inspect invoices, GST split & dispatch.",
                "url": "/reports/sales/",
            },
            {
                "title": "Outstanding & Payments",
                "desc": "Verify dues and payment allocations.",
                "url": "/payments/",
            },
            {
                "title": "Audit Log",
                "desc": "Independent review of all write actions.",
                "url": "/audit/",
            },
        ],
        Role.OWNER: [
            {
                "title": "Stock Summary",
                "desc": "Monitor inventory balances & valuation.",
                "url": "/inventory/",
            },
            {
                "title": "Production Runs",
                "desc": "Review yield & material variances.",
                "url": "/production/",
            },
            {
                "title": "Stock Ledger",
                "desc": "Audit movement history.",
                "url": "/inventory/ledger/",
            },
            {
                "title": "Master Catalog",
                "desc": "View items, customers, and prices.",
                "url": "/masters/items/",
            },
            {
                "title": "Dashboard & Reports",
                "desc": "Orders, stock alerts, dues and registers.",
                "url": "/reports/",
            },
            {
                "title": "Invoices & Outstanding",
                "desc": "Revenue, GST and receivables visibility.",
                "url": "/sales/invoices/",
            },
            {
                "title": "Audit Log",
                "desc": "Read-only trail of significant actions.",
                "url": "/audit/",
            },
        ],
    }

    cards = role_cards.get(role, [])
    return render(
        request,
        "accounts/landing.html",
        {
            "role_display": user.get_role_display(),
            "cards": cards,
        },
    )
