"""PWA REST API URLs."""
from django.urls import path

from apps.sales.api_views import api_order_status, api_submit_order

urlpatterns = [
    path("", api_submit_order, name="pwa-submit-order"),
    path("<int:pk>/", api_order_status, name="pwa-order-status"),
]
