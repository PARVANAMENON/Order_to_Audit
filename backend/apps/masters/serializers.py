"""DRF serializers for masters."""

from rest_framework import serializers

from apps.masters.models import Customer, Item, PriceList, Supplier, Unit, UnitConversion


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ["id", "code", "name"]


class UnitConversionSerializer(serializers.ModelSerializer):
    from_unit_code = serializers.CharField(source="from_unit.code", read_only=True)
    to_unit_code = serializers.CharField(source="to_unit.code", read_only=True)

    class Meta:
        model = UnitConversion
        fields = ["id", "from_unit", "from_unit_code", "to_unit", "to_unit_code", "factor"]


class ItemSerializer(serializers.ModelSerializer):
    base_unit_code = serializers.CharField(source="base_unit.code", read_only=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "sku",
            "name",
            "item_type",
            "base_unit",
            "base_unit_code",
            "display_unit",
            "hsn",
            "gst_rate",
            "tolerance_pct",
            "is_active",
        ]


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "code", "name", "gstin", "state", "assigned_salesman", "phone", "is_active"]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "code", "name", "gstin", "state", "phone", "is_active"]


class PriceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceList
        fields = ["id", "item", "customer", "unit", "rate", "effective_from", "is_active"]
