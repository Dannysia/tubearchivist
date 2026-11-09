"""test serving downscale encodes and archived thumbnails"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from common import views_static
from common.src.env_settings import EnvironmentSettings
from rest_framework.test import APIRequestFactory, force_authenticate
from user.models import Account

DIGEST = "ab" + "0" * 62


@pytest.fixture(name="cache_dir")
def fixture_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(EnvironmentSettings, "CACHE_DIR", str(tmp_path))
    return tmp_path


def _get(view, url, headers=None, **kwargs):
    request = APIRequestFactory().get(url, headers=headers or {})
    force_authenticate(request, user=Account(name="test"))
    return view.as_view()(request, **kwargs)


def _downscale(file_name, headers=None):
    url = f"/media/downscale/{file_name}"
    view = views_static.DownscaleStreamView
    return _get(view, url, headers, file_name=file_name)


def _history(prefix, digest):
    url = f"/media/history/{prefix}/{digest}.jpg"
    view = views_static.HistoryThumbView
    return _get(view, url, prefix=prefix, digest=digest)


def test_downscale_streams_a_range(cache_dir):
    (cache_dir / "downscale").mkdir()
    (cache_dir / "downscale" / "abcdefghijk_720p.mp4").write_bytes(
        b"0123456789"
    )

    response = _downscale("abcdefghijk_720p.mp4", {"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert response["Content-Type"] == "video/mp4"
    assert response["Content-Range"] == "bytes 2-5/10"
    assert response["Content-Length"] == "4"


@pytest.mark.parametrize(
    "file_name",
    [
        "..%2Fsecret.mp4",
        "abcdefghijk.mp4",
        "abcdefghijk_720p.mkv",
        "short_720p.mp4",
    ],
)
def test_downscale_rejects_other_file_names(cache_dir, file_name):
    assert _downscale(file_name).status_code == 400


def test_downscale_missing_file_is_404(cache_dir):
    assert _downscale("abcdefghijk_720p.mp4").status_code == 404


def test_history_serves_the_archived_image(cache_dir):
    folder = cache_dir / "history" / "ab"
    folder.mkdir(parents=True)
    (folder / f"{DIGEST}.jpg").write_bytes(b"\xff\xd8jpeg")

    response = _history("ab", DIGEST)

    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert response.content == b"\xff\xd8jpeg"


def test_history_names_webp_as_webp(cache_dir):
    folder = cache_dir / "history" / "ab"
    folder.mkdir(parents=True)
    (folder / f"{DIGEST}.jpg").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")

    assert _history("ab", DIGEST)["Content-Type"] == "image/webp"


@pytest.mark.parametrize(
    "prefix,digest",
    [("cd", DIGEST), ("ab", "ab" + "0" * 61), ("ab", "AB" + "0" * 62)],
)
def test_history_rejects_a_bad_digest(cache_dir, prefix, digest):
    assert _history(prefix, digest).status_code == 400


def test_history_missing_file_is_404(cache_dir):
    assert _history("ab", DIGEST).status_code == 404


def test_media_needs_a_login(cache_dir):
    request = APIRequestFactory().get(f"/media/history/ab/{DIGEST}.jpg")
    view = views_static.HistoryThumbView.as_view()
    response = view(request, prefix="ab", digest=DIGEST)

    assert response.status_code in (401, 403)


def test_downscale_list_links_to_media_routes():
    from common.src.search_processor import SearchProcess

    hit = {
        "_index": "ta_downscale",
        "_id": "abcdefghijk",
        "_source": {
            "youtube_id": "abcdefghijk",
            "channel_id": "UC" + "x" * 22,
            "vid_thumb_url": "https://i.ytimg.com/vi/abcdefghijk/hq.jpg",
            "media_url": "/youtube/UCxxxxxxxxxxxxxxxxxxxxxx/abcdefghijk.mp4",
            "tmp_file_path": "/cache/downscale/abcdefghijk_720p.mp4",
        },
    }

    job = SearchProcess(hit).process()

    assert job["vid_thumb_url"] == "/media/thumb/video/abcdefghijk.jpg"
    assert job["media_url"] == (
        "/media/stream/UCxxxxxxxxxxxxxxxxxxxxxx/abcdefghijk.mp4"
    )
    assert job["new_media_url"] == "/media/downscale/abcdefghijk_720p.mp4"
    assert job["tmp_file_path"] == "/cache/downscale/abcdefghijk_720p.mp4"
