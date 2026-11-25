"""Shared pytest fixtures for Order-to-Audit tests."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.accounts.models import User


@pytest.fixture
def seeded_db(db) -> dict[str, User]:
    """Run seed_benchmark and return seeded test users by username."""
    call_command("seed_benchmark")
    return {u.username: u for u in User.objects.all()}
