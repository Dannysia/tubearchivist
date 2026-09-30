"""test what a failed state write does to the extraction run"""

import pytest
from common.src.queue_interact import QueueDocMissing, QueueWriteError
from download.src import extraction_queue as eq
from download.src.extraction_queue import ExtractionQueue

MAX_PASSES = 25


def _doc(name, auto_start=False):
    return {
        "item_type": "channel",
        "youtube_id": f"UC_{name}",
        "vid_type": None,
        "limit": None,
        "auto_start": auto_start,
        "flat": False,
        "force": False,
        "target_status": "pending",
    }


class Recorder:
    calls: list = []
    raises: dict = {}

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
        self._run("mark_failed")

    def mark_pending(self):
        self._run("mark_pending")

    def delete_item(self):
        self._run("delete_item")


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    Recorder.calls = []
    Recorder.raises = {}
    monkeypatch.setattr(eq, "ExtractionInteract", Recorder)

    class FakePending:
        extraction_failed = False
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


def _queue(monkeypatch, pending: list[str]):
    remaining = list(pending)
    passes = {"n": 0}

    def fake_next():
        passes["n"] += 1
        if passes["n"] > MAX_PASSES or not remaining:
            return None, None

        name = remaining.pop(0)
        return name, _doc(name)

    monkeypatch.setattr(ExtractionQueue, "_get_next", staticmethod(fake_next))

    return ExtractionQueue(), passes


def test_a_clean_run_resolves_every_entry(monkeypatch):
    queue, _ = _queue(monkeypatch, ["a", "b", "c"])

    resolved, failed, _ = queue.run_queue()

    assert (resolved, failed) == (3, 0)
    assert [c for c in Recorder.calls if c[0] == "delete_item"] == [
        ("delete_item", "a"),
        ("delete_item", "b"),
        ("delete_item", "c"),
    ]


def test_an_entry_deleted_before_it_starts_is_skipped(monkeypatch):
    queue, _ = _queue(monkeypatch, ["a", "b", "c"])
    Recorder.raises[("mark_extracting", "b")] = QueueDocMissing("gone")

    resolved, failed, _ = queue.run_queue()

    assert ("delete_item", "b") not in Recorder.calls
    assert ("mark_extracting", "c") in Recorder.calls
    assert (resolved, failed) == (2, 0)


def test_a_write_failure_stops_the_run_without_raising(monkeypatch):
    queue, passes = _queue(monkeypatch, ["a", "b", "c"])
    Recorder.raises[("mark_extracting", "b")] = QueueWriteError("es down")

    resolved, failed, _ = queue.run_queue()

    assert resolved == 1, "a resolved before the failure"
    assert failed == 0
    assert passes["n"] < MAX_PASSES, "the loop terminated on its own"
    assert ("mark_extracting", "c") not in Recorder.calls


def test_a_failed_delete_stops_the_run(monkeypatch):
    queue, passes = _queue(monkeypatch, ["a", "b"])
    Recorder.raises[("delete_item", "a")] = QueueWriteError("es down")

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
    queue, _ = _queue(monkeypatch, ["a", "b"])
    queue.task = StopsDuringFirstEntry()

    resolved, failed, _ = queue.run_queue()

    assert ("mark_pending", "a") in Recorder.calls
    assert ("delete_item", "a") not in Recorder.calls
    assert ("mark_extracting", "b") not in Recorder.calls
    assert (resolved, failed) == (0, 0)
