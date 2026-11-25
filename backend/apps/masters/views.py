"""Views and API endpoints for masters."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from rest_framework import viewsets

from apps.accounts.models import Role
from apps.accounts.permissions import HasRolePermission, role_required
from apps.masters.models import Customer, Item, PriceList, Supplier, Unit, UnitConversion
from apps.masters.serializers import (
    CustomerSerializer,
    ItemSerializer,
    PriceListSerializer,
    SupplierSerializer,
    UnitConversionSerializer,
    UnitSerializer,
)

ALL_ROLES = (Role.SALESMAN, Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)


@role_required(*ALL_ROLES)
def item_list_view(request: HttpRequest) -> HttpResponse:
    """Display active master items and unit conversions."""
    items = Item.objects.select_related("base_unit", "display_unit").all()
    conversions = UnitConversion.objects.select_related("from_unit", "to_unit").all()
    prices = PriceList.objects.select_related("item", "customer", "unit").filter(is_active=True)
    return render(
        request,
        "masters/items.html",
        {"items": items, "conversions": conversions, "prices": prices},
    )


@role_required(*ALL_ROLES)
def customer_list_view(request: HttpRequest) -> HttpResponse:
    """Display customers (salesmen see their assigned customers first/filtered)."""
    qs = Customer.objects.select_related("assigned_salesman").all()
    if request.user.role == Role.SALESMAN and not request.user.is_superuser:
        qs = qs.filter(assigned_salesman=request.user)
    return render(request, "masters/customers.html", {"customers": qs})


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_classes = [HasRolePermission]
    allowed_roles = (Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            self.allowed_roles = (Role.ADMIN,)
        return super().get_permissions()


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.select_related("base_unit", "display_unit").all()
    serializer_class = ItemSerializer
    permission_classes = [HasRolePermission]
    allowed_roles = ALL_ROLES

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            self.allowed_roles = (Role.ADMIN,)
        return super().get_permissions()


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [HasRolePermission]
    allowed_roles = ALL_ROLES

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role == Role.SALESMAN and not self.request.user.is_superuser:
            return qs.filter(assigned_salesman=self.request.user)
        return qs

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            self.allowed_roles = (Role.ADMIN,)
        return super().get_permissions()


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [HasRolePermission]
    allowed_roles = (Role.ADMIN, Role.PRODUCTION, Role.AUDITOR, Role.OWNER)

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            self.allowed_roles = (Role.ADMIN,)
        return super().get_permissions()


class UnitConversionViewSet(viewsets.ModelViewSet):
    queryset = UnitConversion.objects.select_related("from_unit", "to_unit").all()
    serializer_class = UnitConversionSerializer
    permission_classes = [HasRolePermission]
    allowed_roles = ALL_ROLES

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            self.allowed_roles = (Role.ADMIN,)
        return super().get_permissions()


class PriceListViewSet(viewsets.ModelViewSet):
    queryset = PriceList.objects.select_related("item", "customer", "unit").all()
    serializer_class = PriceListSerializer
    permission_classes = [HasRolePermission]
    allowed_roles = ALL_ROLES

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            self.allowed_roles = (Role.ADMIN,)
        return super().get_permissions()
