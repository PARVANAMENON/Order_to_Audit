"""URL routes for production."""

from django.urls import path

from apps.production.views import (
    production_create_view,
    production_detail_view,
    production_list_view,
    production_save_and_post_view,
)

app_name = "production"

urlpatterns = [
    path("", production_list_view, name="list"),
    path("new/", production_create_view, name="create"),
    path("<int:pk>/", production_detail_view, name="detail"),
    path("<int:pk>/post/", production_save_and_post_view, name="save-and-post"),
]
