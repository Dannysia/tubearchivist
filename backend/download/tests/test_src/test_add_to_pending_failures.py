"""test that videos which did not reach the download queue fail the entry"""

from types import SimpleNamespace

import pytest
from common.src import es_connect
from download.src import queue
from download.src.queue import PendingList


def _handler(monkeypatch, answer):
    class Wrap:
        def __init__(self, path):
            pass

        def post(self, data=None, ndjson=False):
            return answer

    monkeypatch.setattr(queue, "ElasticWrap", Wrap)

    monkeypatch.setattr(es_connect, "ElasticWrap", Wrap)
    cleared = []
    handler = SimpleNamespace(
        missing_videos=[{"youtube_id": "vid1"}, {"youtube_id": "vid2"}],
        auto_start=False,
        extraction_failed=False,
        extraction_error=None,
        cleared=cleared,
        _notify_empty=lambda: None,
        _notify_start=lambda total: None,
        _notify_done=lambda total: None,
        _notify_fail=lambda *a: None,
        _clear_failed_extractions=cleared.extend,
    )
    handler._queue_write_failed = lambda detail: (
        PendingList._queue_write_failed(handler, detail)
    )
    return handler


def test_a_rejected_bulk_write_fails_the_entry(monkeypatch):
    handler = _handler(monkeypatch, ({"error": "x"}, 503))

    added = PendingList.add_to_pending(handler)

    assert added == 0
    assert handler.extraction_failed is True
    assert "503" in handler.extraction_error
    assert handler.cleared == []


def test_items_that_did_not_land_fail_the_entry(monkeypatch):
    answer = {
        "errors": True,
        "items": [
            {"index": {"_id": "vid1", "result": "created"}},
            {"index": {"_id": "vid2", "error": {"type": "x"}}},
        ],
    }
    handler = _handler(monkeypatch, (answer, 200))

    added = PendingList.add_to_pending(handler)

    assert added == 1
    assert handler.extraction_failed is True
    assert "vid2" in handler.extraction_error
    assert "vid1" not in handler.extraction_error
    assert handler.cleared == ["vid1"]


@pytest.mark.parametrize("code", [200, 201])
def test_a_clean_write_leaves_the_entry_alone(monkeypatch, code):
    handler = _handler(monkeypatch, ({"errors": False}, code))

    added = PendingList.add_to_pending(handler)

    assert added == 2
    assert handler.extraction_failed is False
    assert handler.cleared == ["vid1", "vid2"]
