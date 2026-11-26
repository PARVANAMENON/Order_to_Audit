"""URL routes for sales."""
from django.urls import path

from apps.sales import views

app_name = "sales"

urlpatterns = [
    path("pwa/", views.pwa_order_view, name="pwa"),
    path("manifest.webmanifest", views.pwa_manifest_view, name="pwa-manifest"),
    path("sw.js", views.pwa_service_worker_view, name="pwa-sw"),
    path("orders/", views.order_list_view, name="order-list"),
    path("orders/new/", views.order_create_view, name="order-create"),
    path("orders/<int:pk>/", views.order_detail_view, name="order-detail"),
    path("orders/<int:pk>/approve/", views.order_approve_view, name="order-approve"),
    path("orders/<int:pk>/reject/", views.order_reject_view, name="order-reject"),
    path("orders/<int:order_pk>/invoice/", views.invoice_create_view, name="invoice-create"),
    path("invoices/", views.invoice_list_view, name="invoice-list"),
    path("invoices/<int:pk>/", views.invoice_detail_view, name="invoice-detail"),
    path("invoices/<int:pk>/pdf/", views.invoice_pdf_view, name="invoice-pdf"),
    path("invoices/<int:invoice_pk>/dispatch/", views.dispatch_view, name="dispatch"),
    path("invoices/<int:invoice_pk>/credit-note/", views.credit_note_view, name="credit-note"),
]
