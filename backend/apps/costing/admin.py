"""Costing admin."""
from django.contrib import admin

from apps.costing.models import OverheadEntry

admin.site.register(OverheadEntry)
