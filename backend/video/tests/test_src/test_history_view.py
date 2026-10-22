# flake8: noqa: E402

import os

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
