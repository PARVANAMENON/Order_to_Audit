"""URL routes for costing."""
from django.urls import path

from apps.costing import views

app_name = "costing"

urlpatterns = [
    path("run/<int:pk>/", views.run_costing_view, name="run-costing"),
]
