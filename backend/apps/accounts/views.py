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
