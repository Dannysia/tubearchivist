"""all video API urls"""

from django.urls import path
from video import views

urlpatterns = [
    path("", views.VideoApiListView.as_view(), name="api-video-list"),
    # before the <slug:video_id> route, a slug matches this path too
    path(
        "downscale-encoders/",
        views.VideoDownscaleEncoderView.as_view(),
        name="api-video-downscale-encoders",
    ),
    path(
        "<slug:video_id>/",
        views.VideoApiView.as_view(),
        name="api-video",
    ),
    path(
        "<slug:video_id>/nav/",
        views.VideoApiNavView.as_view(),
        name="api-video-nav",
    ),
    path(
        "<slug:video_id>/downscale/",
        views.VideoDownscaleView.as_view(),
        name="api-video-downscale",
    ),
    path(
        "<slug:video_id>/progress/",
        views.VideoProgressView.as_view(),
        name="api-video-progress",
    ),
    path(
        "<slug:video_id>/comment/",
        views.VideoCommentView.as_view(),
        name="api-video-comment",
    ),
    path(
        "<slug:video_id>/similar/",
        views.VideoSimilarView.as_view(),
        name="api-video-similar",
    ),
]
