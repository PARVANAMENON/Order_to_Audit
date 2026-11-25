"""App configuration for bom."""

from django.apps import AppConfig


class BomConfig(AppConfig):
    """Configuration for the Bill of Materials application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bom"
