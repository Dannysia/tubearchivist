"""all download API urls"""

from django.urls import path
from download import views

urlpatterns = [
    path("", views.DownloadApiListView.as_view(), name="api-download-list"),
    path(
        "aggs/",
        views.DownloadAggsApiView.as_view(),
        name="api-download-aggs",
    ),
    path(
        "extraction/",
        views.ExtractionApiListView.as_view(),
        name="api-extraction-list",
    ),
    path(
        "extraction/<slug:extraction_id>/",
        views.ExtractionApiView.as_view(),
        name="api-extraction",
    ),
    path(
        "<slug:video_id>/",
        views.DownloadApiView.as_view(),
        name="api-download",
    ),
]
