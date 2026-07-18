"""all downscale API urls"""

from django.urls import path
from downscale import views

urlpatterns = [
    path(
        "",
        views.DownscaleApiListView.as_view(),
        name="api-downscale-list",
    ),
]
