"""Root URL configuration for Order-to-Audit."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("masters/", include("apps.masters.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("purchasing/", include("apps.purchasing.urls")),
]
