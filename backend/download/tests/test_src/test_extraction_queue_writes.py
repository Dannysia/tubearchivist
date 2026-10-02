"""test what a failed state write does to the extraction run"""

import pytest
from common.src.es_connect import IndexWriteError
from common.src.queue_interact import QueueDocMissing
from download.src import extraction_queue as eq
from download.src.extraction_queue import ExtractionQueue
from download.tests.extraction_helpers import MAX_PASSES, entry_doc, queue_of


class Recorder:
    calls: list = []
    raises: dict = {}
    messages: list = []

    def __init__(self, doc_id):
        self.doc_id = doc_id

    def _run(self, name):
        Recorder.calls.append((name, self.doc_id))
        err = Recorder.raises.get((name, self.doc_id))
        if err:
            raise err

    def mark_extracting(self):
        self._run("mark_extracting")

    def mark_failed(self, message):
        Recorder.messages.append(message)
        self._run("mark_failed")

    def mark_pending(self):
        self._run("mark_pending")

    def delete_item(self):
        self._run("delete_item")


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    Recorder.calls = []
    Recorder.raises = {}
    Recorder.messages = []
    monkeypatch.setattr(eq, "ExtractionInteract", Recorder)

    class FakePending:
        extraction_failed = False
        extraction_error = None
        failed_videos: list = []
        all_pending: list = []
        all_ignored: list = []
        to_skip: list = []
        all_videos: list = []
        all_channels: list = []
        channel_overwrites: dict = {}

        def __init__(self, youtube_ids, task=None, **kwargs):
            pass

        def get_download(self):
            pass

        def get_indexed(self):
            pass

        def get_channels(self):
            pass

        def parse_url_list(self, status="pending"):
            pass

    monkeypatch.setattr(eq, "PendingList", FakePending)

    return Recorder


def test_a_clean_run_resolves_every_entry(monkeypatch):
    queue, _ = queue_of(monkeypatch, ["a", "b", "c"])

    resolved, failed, _ = queue.run_queue()

    assert (resolved, failed) == (3, 0)
    assert [c for c in Recorder.calls if c[0] == "delete_item"] == [
        ("delete_item", "a"),
        ("delete_item", "b"),
        ("delete_item", "c"),
    ]


def test_an_entry_deleted_before_it_starts_is_skipped(monkeypatch):
    queue, _ = queue_of(monkeypatch, ["a", "b", "c"])
    Recorder.raises[("mark_extracting", "b")] = QueueDocMissing("gone")

    resolved, failed, _ = queue.run_queue()

    assert ("delete_item", "b") not in Recorder.calls
    assert ("mark_extracting", "c") in Recorder.calls
    assert (resolved, failed) == (2, 0)


def test_a_write_failure_stops_the_run_without_raising(monkeypatch):
    queue, passes = queue_of(monkeypatch, ["a", "b", "c"])
    Recorder.raises[("mark_extracting", "b")] = IndexWriteError("es down")

    resolved, failed, _ = queue.run_queue()

    assert resolved == 1, "a resolved before the failure"
    assert failed == 0
    assert passes["n"] < MAX_PASSES, "the loop terminated on its own"
    assert ("mark_extracting", "c") not in Recorder.calls


def test_a_failed_delete_stops_the_run(monkeypatch):
    queue, passes = queue_of(monkeypatch, ["a", "b"])
    Recorder.raises[("delete_item", "a")] = IndexWriteError("es down")

    resolved, _, _ = queue.run_queue()

    assert resolved == 1
    assert passes["n"] < MAX_PASSES
    assert ("mark_extracting", "b") not in Recorder.calls


class StopsDuringFirstEntry:
    def __init__(self):
        self.checks = 0

    def is_stopped(self):
        self.checks += 1
        return self.checks > 1


def test_a_stop_mid_entry_puts_it_back_to_pending(monkeypatch):
    queue, _ = queue_of(monkeypatch, ["a", "b"])
    queue.task = StopsDuringFirstEntry()

    resolved, failed, _ = queue.run_queue()

    assert ("mark_pending", "a") in Recorder.calls
    assert ("delete_item", "a") not in Recorder.calls
    assert ("mark_extracting", "b") not in Recorder.calls
    assert (resolved, failed) == (0, 0)


def test_recorded_failed_videos_add_up_over_the_run(monkeypatch):
    queue, _ = queue_of(monkeypatch, ["a", "b"])
    monkeypatch.setattr(
        ExtractionQueue, "record_failed_videos", lambda self, *a: 2
    )

    queue.run_queue()

    assert queue.videos_failed == 4


def test_a_failed_entry_keeps_the_extraction_error(monkeypatch):
    queue, _ = queue_of(monkeypatch, ["a"])
    monkeypatch.setattr(eq.PendingList, "extraction_failed", True)
    monkeypatch.setattr(eq.PendingList, "extraction_error", "members only")

    queue.run_queue()

    assert Recorder.messages == ["members only"]


def test_a_failed_entry_without_an_error_points_to_the_logs(monkeypatch):
    queue, _ = queue_of(monkeypatch, ["a"])
    monkeypatch.setattr(eq.PendingList, "extraction_failed", True)

    queue.run_queue()

    assert Recorder.messages == ["extraction failed, see logs"]


def test_an_entrys_failed_videos_are_recorded(monkeypatch):
    queue, _ = queue_of(monkeypatch, ["a"])
    failed = [{"url": "vid1", "vid_type": "videos", "error": "x"}]
    monkeypatch.setattr(eq.PendingList, "failed_videos", failed)
    recorded = []
    monkeypatch.setattr(
        ExtractionQueue,
        "record_failed_videos",
        lambda self, videos, parent: recorded.append((videos, parent)) or 0,
    )

    queue.run_queue()

    assert recorded == [(failed, entry_doc("a"))]
