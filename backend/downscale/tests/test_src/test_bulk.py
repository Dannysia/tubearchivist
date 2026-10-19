from types import SimpleNamespace

import pytest
from downscale.src import bulk


class FakeRedis:
    store: dict = {}

    def set_message(self, key, message, expire=False):
        self.store[key] = message

    def get_message_dict(self, key):
        return self.store.get(key, {})

    def list_keys(self, query):
        return [key for key in self.store if key.startswith(query)]

    def del_message(self, key):
        return bool(self.store.pop(key, None))


@pytest.fixture(name="redis", autouse=True)
def fixture_redis(monkeypatch):
    FakeRedis.store = {}
    monkeypatch.setattr(bulk, "RedisArchivist", FakeRedis)
    monkeypatch.setattr(bulk.celery_app, "send_task", lambda *a, **k: None)
    monkeypatch.setattr(
        bulk,
        "TaskManager",
        lambda: SimpleNamespace(get_task=lambda task_id: {}),
    )
    return FakeRedis.store


def _task(task_id, stop_after=None):
    calls = {"count": 0}

    def is_stopped():
        calls["count"] += 1
        return stop_after is not None and calls["count"] > stop_after

    return SimpleNamespace(
        request=SimpleNamespace(id=task_id), is_stopped=is_stopped
    )


def _reviews(monkeypatch, outcomes):
    def review(doc_id):
        outcome = outcomes[doc_id]

        def act():
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return SimpleNamespace(accept=act, reject=act)

    monkeypatch.setattr(bulk, "DownscaleReview", review)


def test_queue_bulk_records_a_queued_state():
    state = bulk.queue_bulk(["one", "two"], "accept")

    assert bulk.get_bulk(state["task_id"])["status"] == "queued"
    assert bulk.get_active_bulk()["task_id"] == state["task_id"]


def test_run_bulk_reports_every_item_and_finishes(monkeypatch):
    _reviews(
        monkeypatch,
        {"one": None, "two": "job not found", "three": RuntimeError("boom")},
    )
    state = bulk.queue_bulk(["one", "two", "three"], "accept")

    summary = bulk.run_bulk(
        _task(state["task_id"]), ["one", "two", "three"], "accept"
    )

    final = bulk.get_bulk(state["task_id"])
    assert final["status"] == "done"
    assert final["done"] == 3
    assert final["failed"] == [
        {"id": "two", "error": "job not found"},
        {"id": "three", "error": "RuntimeError: boom"},
    ]
    assert summary == "Bulk accept: 1 of 3 jobs succeeded, 2 failed"
    assert bulk.get_active_bulk() is None


def test_run_bulk_stops_when_asked(monkeypatch):
    _reviews(monkeypatch, {"one": None, "two": None, "three": None})
    state = bulk.queue_bulk(["one", "two", "three"], "reject")

    summary = bulk.run_bulk(
        _task(state["task_id"], stop_after=1),
        ["one", "two", "three"],
        "reject",
    )

    final = bulk.get_bulk(state["task_id"])
    assert final["done"] == 1
    assert final["stopped"] is True
    assert summary.endswith("stopped early")


def test_a_dead_task_reads_as_failed_and_not_active(monkeypatch):
    state = bulk.queue_bulk(["one"], "accept")
    monkeypatch.setattr(
        bulk,
        "TaskManager",
        lambda: SimpleNamespace(
            get_task=lambda task_id: {
                "status": "FAILURE",
                "result": {
                    "exc_type": "WorkerLostError",
                    "exc_message": ["Worker exited prematurely"],
                },
            }
        ),
    )

    final = bulk.get_bulk(state["task_id"])

    assert final["status"] == "failed"
    assert final["failure"] == "WorkerLostError: Worker exited prematurely"
    assert bulk.get_active_bulk() is None


def test_startup_clears_queued_but_not_finished_bulks(monkeypatch):
    _reviews(monkeypatch, {"one": None})
    queued = bulk.queue_bulk(["one"], "accept")
    finished = bulk.queue_bulk(["one"], "accept")
    bulk.run_bulk(_task(finished["task_id"]), ["one"], "accept")

    assert bulk.clear_queued_bulks() == 1
    assert bulk.get_bulk(queued["task_id"]) is None
    assert bulk.get_bulk(finished["task_id"])["status"] == "done"


def test_the_state_has_no_top_level_error_the_frontend_would_drop():
    state = bulk.queue_bulk(["one"], "accept")

    assert "error" not in state
