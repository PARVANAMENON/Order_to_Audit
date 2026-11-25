"""URL routes for masters."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.masters.views import (
    CustomerViewSet,
    ItemViewSet,
    PriceListViewSet,
    SupplierViewSet,
    UnitConversionViewSet,
    UnitViewSet,
    customer_list_view,
    item_list_view,
)

app_name = "masters"

router = DefaultRouter()
router.register("units", UnitViewSet, basename="unit")
router.register("conversions", UnitConversionViewSet, basename="unit-conversion")
router.register("items", ItemViewSet, basename="item")
router.register("customers", CustomerViewSet, basename="customer")
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("prices", PriceListViewSet, basename="price-list")

urlpatterns = [
    path("items/", item_list_view, name="item-list"),
    path("customers/", customer_list_view, name="customer-list"),
    path("api/", include(router.urls)),
]
