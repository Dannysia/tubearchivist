# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from download.src import queue
from download.src.queue import PendingList
from download.src.thumbnails import ThumbManagerBase
from PIL import Image

VIDEO_ID = "abc123xyz00"
META = {"id": VIDEO_ID, "title": "t", "channel": "c", "channel_id": "UC1"}


def _extract(monkeypatch, cache, fetched):
    monkeypatch.setattr(ThumbManagerBase, "CACHE_DIR", str(cache))
    monkeypatch.setattr(ThumbManagerBase, "VIDEO_DIR", str(cache / "videos"))
    monkeypatch.setattr(
        ThumbManagerBase, "download_raw", lambda self, url: fetched(url)
    )
    monkeypatch.setattr(
        queue,
        "YoutubeVideo",
        lambda youtube_id: SimpleNamespace(
            youtube_meta=dict(META),
            get_from_youtube=lambda: None,
        ),
    )
    handler = SimpleNamespace(
        videos_attempted=0,
        _parse_entry=lambda youtube_id, video_data: {
            "vid_thumb_url": "https://i.ytimg.com/vi/x/maxres.jpg"
        },
    )
    return PendingList._extract_video(handler, VIDEO_ID, None)


def test_queueing_an_indexed_video_keeps_its_cached_thumbnail(
    tmp_path, monkeypatch
):
    folder = tmp_path / "videos" / "a"
    folder.mkdir(parents=True)
    (folder / f"{VIDEO_ID}.jpg").write_bytes(b"current")
    fetched = []

    _extract(monkeypatch, tmp_path, fetched.append)

    assert fetched == []
    assert (folder / f"{VIDEO_ID}.jpg").read_bytes() == b"current"


def test_queueing_a_new_video_downloads_its_thumbnail(tmp_path, monkeypatch):
    _extract(monkeypatch, tmp_path, lambda url: Image.new("RGB", (1280, 720)))

    assert (tmp_path / "videos" / "a" / f"{VIDEO_ID}.jpg").exists()
