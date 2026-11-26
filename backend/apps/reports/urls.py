"""Reports URL conf."""
from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("sales/", views.sales_register_view, name="sales-register"),
    path("gst/", views.gst_summary_view, name="gst-summary"),
    path("purchases/", views.purchase_register_view, name="purchase-register"),
    path("production/", views.production_variance_report_view, name="production-variance"),
    path("stock/", views.stock_ledger_report_view, name="stock-ledger"),
    path("outstanding/", views.outstanding_report_view, name="outstanding"),
]
