"""all downscale API urls"""

from django.urls import path
from downscale import views, worker_views

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
    path(
        "worker/claim/",
        worker_views.DownscaleWorkerClaimView.as_view(),
        name="api-downscale-worker-claim",
    ),
    path(
        "worker/jobs/<str:doc_id>/heartbeat/",
        worker_views.DownscaleWorkerHeartbeatView.as_view(),
        name="api-downscale-worker-heartbeat",
    ),
    path(
        "worker/jobs/<str:doc_id>/result/",
        worker_views.DownscaleWorkerResultView.as_view(),
        name="api-downscale-worker-result",
    ),
    path(
        "worker/jobs/<str:doc_id>/finish/",
        worker_views.DownscaleWorkerFinishView.as_view(),
        name="api-downscale-worker-finish",
    ),
    path(
        "worker/jobs/<str:doc_id>/fail/",
        worker_views.DownscaleWorkerFailView.as_view(),
        name="api-downscale-worker-fail",
    ),
    path(
        "worker/jobs/<str:doc_id>/",
        worker_views.DownscaleWorkerDeleteView.as_view(),
        name="api-downscale-worker-delete",
    ),
]
