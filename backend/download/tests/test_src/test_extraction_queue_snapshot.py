"""test how the extraction run keeps to_skip current between entries"""

import pytest
from download.src import extraction_queue as eq
from download.src import queue as queue_module
from download.src.extraction_queue import ExtractionQueue
from download.src.queue import PendingIndex

MAX_PASSES = 25


def _doc(name):
    return {
        "item_type": "channel",
        "youtube_id": f"UC_{name}",
        "vid_type": None,
        "limit": None,
        "auto_start": False,
        "flat": False,
        "force": False,
        "target_status": "pending",
    }


class FakeES:
    download: list = []
    indexed: list = []


class FakePaginate:
    def __init__(self, index, data, **kwargs):
        self.index = index

    def get_results(self):
        if self.index == "ta_download":
            return list(FakeES.download)

        return list(FakeES.indexed)


class FakePending(PendingIndex):
    extraction_failed = False
    seen: list = []
    on_parse = None

    def __init__(self, youtube_ids, task=None, **kwargs):
        super().__init__()

    def get_channels(self):
        self.all_channels = []
        self.channel_overwrites = {}

    def parse_url_list(self, status="pending"):
        FakePending.seen.append(sorted(self.to_skip))
        if FakePending.on_parse:
            FakePending.on_parse(self)


class Interact:
    def __init__(self, doc_id):
        pass

    def mark_extracting(self):
        return None

    def mark_failed(self, message):
        return None

    def delete_item(self):
        return None


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    FakeES.download = []
    FakeES.indexed = []
    FakePending.seen = []
    FakePending.on_parse = None
    FakePending.extraction_failed = False
    monkeypatch.setattr(queue_module, "IndexPaginate", FakePaginate)
    monkeypatch.setattr(eq, "PendingList", FakePending)
    monkeypatch.setattr(eq, "ExtractionInteract", Interact)


def _queue(monkeypatch, entries: list[str]):
    remaining = list(entries)
    passes = {"n": 0}

    def fake_next():
        passes["n"] += 1
        if passes["n"] > MAX_PASSES or not remaining:
            return None, None

        name = remaining.pop(0)
        return name, _doc(name)

    monkeypatch.setattr(ExtractionQueue, "_get_next", staticmethod(fake_next))

    return ExtractionQueue()


def _on_first_parse(action):
    def on_parse(handler):
        if len(FakePending.seen) == 1:
            action(handler)

    return on_parse


def test_an_ignore_set_mid_run_reaches_the_next_entry(monkeypatch):
    queue = _queue(monkeypatch, ["a", "b"])
    FakePending.on_parse = _on_first_parse(
        lambda handler: FakeES.download.append(
            {"youtube_id": "ignored1", "status": "ignore"}
        )
    )

    queue.run_queue()

    first, second = FakePending.seen
    assert "ignored1" not in first
    assert "ignored1" in second


def test_a_failed_entry_still_refreshes_for_the_next(monkeypatch):
    queue = _queue(monkeypatch, ["a", "b"])

    def fail_and_ignore(handler):
        handler.extraction_failed = True
        FakeES.download.append({"youtube_id": "ignored1", "status": "ignore"})

    FakePending.on_parse = _on_first_parse(fail_and_ignore)

    resolved, failed, _ = queue.run_queue()

    assert (resolved, failed) == (1, 1)
    assert "ignored1" in FakePending.seen[1]


def test_a_video_that_leaves_the_queue_mid_run_stays_skipped(monkeypatch):
    FakeES.download = [{"youtube_id": "queued1", "status": "pending"}]
    queue = _queue(monkeypatch, ["a", "b"])
    FakePending.on_parse = _on_first_parse(
        lambda handler: FakeES.download.clear()
    )

    queue.run_queue()

    assert "queued1" in FakePending.seen[1]


def test_the_indexed_videos_survive_every_refresh(monkeypatch):
    FakeES.indexed = [{"youtube_id": "indexed1"}]
    queue = _queue(monkeypatch, ["a", "b", "c"])

    queue.run_queue()

    assert len(FakePending.seen) == 3
    assert all("indexed1" in entry for entry in FakePending.seen)
