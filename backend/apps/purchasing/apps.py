"""App configuration for purchasing."""

from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    """Configuration for the purchasing application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.purchasing"
