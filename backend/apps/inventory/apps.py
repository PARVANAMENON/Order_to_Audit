"""App configuration for inventory."""

from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """Configuration for the inventory ledger application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
