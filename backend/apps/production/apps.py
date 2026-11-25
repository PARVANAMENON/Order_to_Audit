"""App configuration for production."""

from django.apps import AppConfig


class ProductionConfig(AppConfig):
    """Configuration for the production runs application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.production"
