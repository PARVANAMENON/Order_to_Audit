"""URL patterns for accounts."""

from django.urls import path

from apps.accounts.views import CustomLoginView, CustomLogoutView, landing_view

app_name = "accounts"

urlpatterns = [
    path("", landing_view, name="landing"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
]
