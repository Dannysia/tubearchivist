"""all downscale API urls"""

from django.urls import path
from downscale import views

urlpatterns = [
    path(
        "",
        views.DownscaleApiListView.as_view(),
        name="api-downscale-list",
    ),
    path(
        "aggs/",
        views.DownscaleAggsApiView.as_view(),
        name="api-downscale-aggs",
    ),
    path(
        "test-encoders/",
        views.DownscaleEncoderTestApiView.as_view(),
        name="api-downscale-test-encoders",
    ),
]
