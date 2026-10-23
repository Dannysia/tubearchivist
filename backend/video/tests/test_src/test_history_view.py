# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from common.src.env_settings import EnvironmentSettings
from download.src import thumbnails
from download.src.thumbnails import ThumbManagerBase
from video import views

VIDEO_ID = "abc123xyz00"


def test_thumbnail_versions_point_at_the_archive_and_the_live_thumb(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(EnvironmentSettings, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(ThumbManagerBase, "CACHE_DIR", str(tmp_path))
    archived = thumbnails.archive_image(b"old picture")
    monkeypatch.setattr(
        views,
        "field_versions",
        lambda item_id, field, first_seen: [
            {"value": "current", "first_seen": 300, "replaced": None},
            {"value": archived, "first_seen": 200, "replaced": 300},
            {"value": "never-archived", "first_seen": 100, "replaced": 200},
        ],
    )

    versions = views._thumbnail_versions(VIDEO_ID, 100)

    root = EnvironmentSettings().get_cache_root()
    assert versions == [
        {
            "first_seen": 300,
            "replaced": None,
            "image_url": f"{root}/videos/a/{VIDEO_ID}.jpg",
        },
        {
            "first_seen": 200,
            "replaced": 300,
            "image_url": f"{root}/history/{archived[:2]}/{archived}.jpg",
        },
        {"first_seen": 100, "replaced": 200, "image_url": None},
    ]


def test_history_versions_only_carry_their_own_field():
    from video.serializers import VideoHistorySerializer

    version = {"first_seen": 100, "replaced": None}
    data = VideoHistorySerializer(
        {
            "title": [{**version, "value": "Title"}],
            "description": [],
            "thumbnail": [{**version, "image_url": "/cache/x.jpg"}],
            "views": [],
            "likes": [],
        }
    ).data

    assert set(data["title"][0]) == {"value", "first_seen", "replaced"}
    assert set(data["thumbnail"][0]) == {"image_url", "first_seen", "replaced"}


def _history_view(monkeypatch, json_data):
    asked = []
    monkeypatch.setattr(
        views,
        "YoutubeVideo",
        lambda video_id: SimpleNamespace(
            json_data=json_data,
            get_from_es=lambda print_error=True: None,
        ),
    )
    monkeypatch.setattr(
        views,
        "field_versions",
        lambda item_id, field, first_seen: asked.append(
            ("versions", item_id, field, first_seen)
        )
        or [],
    )
    monkeypatch.setattr(
        views,
        "numeric_series",
        lambda item_id, field, first_seen: asked.append(
            ("series", item_id, field, first_seen)
        )
        or [],
    )
    response = views.VideoHistoryView().get(None, VIDEO_ID)
    return response, asked


def test_history_asks_for_each_tracked_field_since_download(monkeypatch):
    response, asked = _history_view(monkeypatch, {"date_downloaded": 123})

    assert response.status_code == 200
    assert set(response.data) == {
        "title",
        "description",
        "thumbnail",
        "views",
        "likes",
    }
    assert sorted(asked) == sorted(
        [
            ("versions", VIDEO_ID, "title", 123),
            ("versions", VIDEO_ID, "description", 123),
            ("versions", VIDEO_ID, "vid_thumb_image", 123),
            ("series", VIDEO_ID, "stats.view_count", 123),
            ("series", VIDEO_ID, "stats.like_count", 123),
        ]
    )


def test_history_of_an_unknown_video_is_not_found(monkeypatch):
    response, asked = _history_view(monkeypatch, None)

    assert response.status_code == 404
    assert asked == []
