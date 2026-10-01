"""test that videos an entry could not extract stay in the queue as failed"""

import json
from types import SimpleNamespace

import pytest
from download.src import extraction_queue as eq
from download.src import queue
from download.src.extraction_queue import ExtractionQueue
from download.src.queue import PendingList

PARENT = {
    "auto_start": True,
    "flat": True,
    "force": True,
    "target_status": "ignore",
}


def _handler():
    return SimpleNamespace(
        task=None,
        videos_failed_count=0,
        extraction_failed=False,
        extraction_error=None,
        failed_videos=[],
    )


def test_a_channel_video_failure_is_kept_with_its_error():
    handler = _handler()

    PendingList._video_failed(
        handler, "vid1", "videos", "Premieres in 2h", False
    )

    assert handler.failed_videos == [
        {"url": "vid1", "vid_type": "videos", "error": "Premieres in 2h"}
    ]
    assert handler.extraction_failed is False


def test_a_single_video_failure_fails_its_own_entry_instead():
    handler = _handler()

    PendingList._video_failed(handler, "vid1", None, "unavailable", True)

    assert handler.failed_videos == []
    assert handler.extraction_failed is True
    assert handler.extraction_error == "unavailable"


class BulkRecorder:
    posts: list = []
    status = 200

    def __init__(self, path):
        self.path = path

    def post(self, data=None, ndjson=False):
        BulkRecorder.posts.append((self.path, data))
        return {"errors": False}, BulkRecorder.status


@pytest.fixture
def bulk(monkeypatch):
    BulkRecorder.posts = []
    BulkRecorder.status = 200
    monkeypatch.setattr(eq, "ElasticWrap", BulkRecorder)
    monkeypatch.setattr(queue, "ElasticWrap", BulkRecorder)
    return BulkRecorder


def test_failed_videos_are_written_as_failed_video_entries(bulk):
    failed = [{"url": "vid1", "vid_type": "videos", "error": "Premieres"}]

    written = ExtractionQueue().record_failed_videos(failed, PARENT)

    assert written == 1
    path, data = bulk.posts[0]
    action, doc = [json.loads(i) for i in data.strip().split("\n")]
    assert path == "_bulk?refresh=true"
    assert action["index"]["_id"] == "video_vid1_videos"
    assert doc["status"] == "failed"
    assert doc["message"] == "Premieres"
    assert doc["item_type"] == "video"
    assert doc["auto_start"] is True
    assert doc["flat"] is True
    assert doc["force"] is True
    assert doc["target_status"] == "ignore"


def test_failed_videos_that_could_not_be_written_count_none(bulk):
    bulk.status = 503
    failed = [{"url": "vid1", "vid_type": "videos", "error": "Premieres"}]

    assert ExtractionQueue().record_failed_videos(failed, PARENT) == 0


def test_nothing_failed_writes_nothing(bulk):
    assert ExtractionQueue().record_failed_videos([], PARENT) == 0
    assert bulk.posts == []


@pytest.mark.parametrize("ok, cleared", [(True, ["vid1"]), (False, [])])
def test_a_video_that_now_extracts_clears_its_failed_entry(
    monkeypatch, ok, cleared
):
    seen = []

    class Wrap:
        def __init__(self, path):
            pass

        def post(self, data=None, ndjson=False):
            return ({"errors": False}, 200) if ok else ({"error": "x"}, 503)

    monkeypatch.setattr(queue, "ElasticWrap", Wrap)
    handler = SimpleNamespace(
        missing_videos=[{"youtube_id": "vid1"}],
        auto_start=False,
        _notify_empty=lambda: None,
        _notify_start=lambda total: None,
        _notify_done=lambda total: None,
        _notify_fail=lambda *a: None,
        _clear_failed_extractions=lambda ids: seen.extend(ids),
        _queue_write_failed=lambda detail: None,
    )

    PendingList.add_to_pending(handler)

    assert seen == cleared


def test_clearing_deletes_only_failed_video_entries_of_those_ids(bulk):
    PendingList._clear_failed_extractions(["vid1", "vid2"])

    path, data = bulk.posts[0]
    assert path == "ta_extraction/_delete_by_query?refresh=true"
    assert data["query"]["bool"]["must"] == [
        {"term": {"item_type": {"value": "video"}}},
        {"term": {"status": {"value": "failed"}}},
        {"terms": {"youtube_id": ["vid1", "vid2"]}},
    ]
