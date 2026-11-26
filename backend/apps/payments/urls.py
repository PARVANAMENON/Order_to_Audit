"""URL routes for payments."""
from django.urls import path

from apps.payments import views

app_name = "payments"

urlpatterns = [
    path("", views.payment_list_view, name="list"),
    path("new/", views.payment_create_view, name="create"),
    path("<int:pk>/", views.payment_detail_view, name="detail"),
]
