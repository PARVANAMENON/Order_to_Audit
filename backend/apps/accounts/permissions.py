"""Server-side role permission mixins, decorators, and DRF permissions."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from rest_framework import permissions

from apps.accounts.models import Role


def _user_has_role(user: Any, allowed_roles: tuple[str, ...]) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", None) in allowed_roles


def role_required(*allowed_roles: str) -> Callable[..., Any]:
    """Decorator enforcing authentication and role membership server-side."""

    def decorator(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @login_required
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if not _user_has_role(request.user, allowed_roles):
                raise PermissionDenied("Your role is not permitted to access this resource.")
            if getattr(request.user, "role", None) == Role.AUDITOR and request.method not in (
                "GET",
                "HEAD",
                "OPTIONS",
            ):
                raise PermissionDenied("Auditor role is strictly read-only.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    """CBV mixin enforcing server-side role access and read-only auditor protection."""

    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.allowed_roles and not _user_has_role(request.user, self.allowed_roles):
            raise PermissionDenied("Your role is not permitted to access this resource.")
        if getattr(request.user, "role", None) == Role.AUDITOR and request.method not in (
            "GET",
            "HEAD",
            "OPTIONS",
        ):
            raise PermissionDenied("Auditor role is strictly read-only.")
        return super().dispatch(request, *args, **kwargs)


class HasRolePermission(permissions.BasePermission):
    """DRF permission checking `view.allowed_roles` and keeping auditor read-only."""

    def has_permission(self, request: HttpRequest, view: Any) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "role", None) == Role.AUDITOR and request.method not in (
            permissions.SAFE_METHODS
        ):
            return False
        allowed_roles = tuple(getattr(view, "allowed_roles", ()))
        if not allowed_roles:
            return True
        return _user_has_role(user, allowed_roles)
