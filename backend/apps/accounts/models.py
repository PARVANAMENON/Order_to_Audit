"""User and role models for Order-to-Audit."""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """Supported application roles."""

    SALESMAN = "salesman", "Salesman"
    ADMIN = "admin", "Admin"
    PRODUCTION = "production", "Production"
    AUDITOR = "auditor", "Auditor"
    OWNER = "owner", "Owner"


class User(AbstractUser):
    """Custom user model with explicit business role."""

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.SALESMAN,
    )
    phone = models.CharField(max_length=20, blank=True)

    @property
    def is_salesman(self) -> bool:
        return self.role == Role.SALESMAN

    @property
    def is_admin_role(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_production(self) -> bool:
        return self.role == Role.PRODUCTION

    @property
    def is_auditor(self) -> bool:
        return self.role == Role.AUDITOR

    @property
    def is_owner(self) -> bool:
        return self.role == Role.OWNER

    def has_any_role(self, roles: tuple[str, ...] | list[str] | set[str]) -> bool:
        """Return True if superuser or user's role is in the allowed set."""
        return bool(self.is_superuser or self.role in roles)

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"
