"""test that queued videos are searchable before the next entry reads"""

from types import SimpleNamespace

from common.src import es_connect
from download.src import queue
from download.src.queue import PendingList


def test_the_bulk_write_refreshes(monkeypatch):
    paths = []

    class Wrap:
        def __init__(self, path):
            paths.append(path)

        def post(self, data=None, ndjson=False):
            return {"errors": False}, 200

    monkeypatch.setattr(queue, "ElasticWrap", Wrap)

    monkeypatch.setattr(es_connect, "ElasticWrap", Wrap)
    handler = SimpleNamespace(
        missing_videos=[{"youtube_id": "video1"}],
        auto_start=False,
        _notify_empty=lambda: None,
        _notify_start=lambda total: None,
        _notify_done=lambda total: None,
        _notify_fail=lambda *a: None,
        _clear_failed_extractions=lambda ids: None,
    )

    PendingList.add_to_pending(handler)

    assert paths == ["_bulk?refresh=true"]
