"""URL routes for inventory."""

from django.urls import path

from apps.inventory.views import (
    adjustment_detail_view,
    stock_adjust_view,
    stock_ledger_view,
    stock_summary_view,
)

app_name = "inventory"

urlpatterns = [
    path("", stock_summary_view, name="summary"),
    path("ledger/", stock_ledger_view, name="ledger"),
    path("adjust/", stock_adjust_view, name="adjust"),
    path("adjust/<int:pk>/", adjustment_detail_view, name="adjustment-detail"),
]
