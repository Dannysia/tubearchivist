"""test that a failed channel listing is not taken for an empty channel"""

from types import SimpleNamespace

import pytest
from channel.src import remote_query
from channel.src.remote_query import get_last_channel_videos
from download.src import queue
from download.src.queue import PendingList
from video.src.constants import VideoTypeEnum

CONFIG = {
    "subscriptions": {
        "channel_size": 5,
        "live_channel_size": 5,
        "shorts_channel_size": 5,
    }
}


@pytest.mark.parametrize(
    "answer, collected",
    [
        ((None, "ERROR: [youtube] unable to download"), 1),
        ((None, None), 0),
    ],
)
def test_the_listing_reports_what_failed(monkeypatch, answer, collected):
    class Wrap:
        def __init__(self, obs, config):
            pass

        def extract(self, url):
            return answer

    monkeypatch.setattr(remote_query, "YtWrap", Wrap)
    errors: list = []

    videos = get_last_channel_videos(
        "UC1", CONFIG, query_filter=VideoTypeEnum.VIDEOS, errors=errors
    )

    assert videos == []
    assert len(errors) == collected


@pytest.mark.parametrize("failed", [True, False])
def test_the_entry_fails_only_when_the_listing_did(monkeypatch, failed):
    def listing(errors=None, **kwargs):
        if failed:
            errors.append("videos: ERROR")
        return []

    monkeypatch.setattr(queue, "get_last_channel_videos", listing)
    handler = SimpleNamespace(
        config=CONFIG, task=None, extraction_failed=False
    )
    entry = {"url": "UC1", "vid_type": "videos", "limit": 5}

    PendingList._parse_channel(handler, entry)

    assert handler.extraction_failed is failed
