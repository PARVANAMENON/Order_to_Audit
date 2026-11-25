"""URL routes for purchasing."""

from django.urls import path

from apps.purchasing.views import (
    purchase_create_view,
    purchase_detail_view,
    purchase_list_view,
    purchase_post_view,
)

app_name = "purchasing"

urlpatterns = [
    path("", purchase_list_view, name="list"),
    path("new/", purchase_create_view, name="create"),
    path("<int:pk>/", purchase_detail_view, name="detail"),
    path("<int:pk>/post/", purchase_post_view, name="post"),
]
