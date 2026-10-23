# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from appsettings.src import reindex
from appsettings.src.reindex import Reindex
from common.src.history import VIDEO_THUMB_IMAGE

VIDEO_ID = "abc123xyz00"


class _Video:
    uploaded: list[dict] = []

    def __init__(self, youtube_id):
        self.youtube_id = youtube_id
        self.json_data = None
        self.youtube_meta = None

    def get_from_es(self):
        self.json_data = {
            "youtube_id": self.youtube_id,
            "title": "Old title",
            "vid_thumb_url": "https://i.ytimg.com/vi/x/old.jpg",
        }

    def build_json(self, media_path):
        self.youtube_meta = {"id": self.youtube_id}
        self.json_data = {
            "youtube_id": self.youtube_id,
            "title": "New title",
            "vid_thumb_url": "https://i.ytimg.com/vi/x/new.jpg",
        }

    def delete_subtitles(self, subtitles):
        pass

    def check_subtitles(self):
        pass

    def upload_to_es(self):
        self.uploaded.append(dict(self.json_data))


def test_a_refresh_records_the_thumbnail_change_without_storing_it(
    monkeypatch,
):
    refreshed, tracked = [], []
    _Video.uploaded = []
    monkeypatch.setattr(reindex, "YoutubeVideo", _Video)
    monkeypatch.setattr(
        reindex,
        "ThumbManager",
        lambda youtube_id: SimpleNamespace(
            refresh_video_thumb=lambda url: refreshed.append(url)
            or ("old-hash", "new-hash")
        ),
    )
    monkeypatch.setattr(
        reindex,
        "track_changes",
        lambda item_type, item_id, old, new, source: tracked.append(
            (old, new, source)
        ),
    )
    monkeypatch.setattr(
        Reindex, "_get_media_path", staticmethod(lambda *args: False)
    )
    handler = Reindex.__new__(Reindex)
    handler.processed = {"videos": 0}

    handler.reindex_single_video(VIDEO_ID)

    assert refreshed == ["https://i.ytimg.com/vi/x/new.jpg"]
    old, new, source = tracked[0]
    assert (old["title"], old[VIDEO_THUMB_IMAGE]) == ("Old title", "old-hash")
    assert (new["title"], new[VIDEO_THUMB_IMAGE]) == ("New title", "new-hash")
    assert source == "reindex"
    assert VIDEO_THUMB_IMAGE not in _Video.uploaded[0]
