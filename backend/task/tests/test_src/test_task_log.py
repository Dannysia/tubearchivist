"""test recording task outcomes"""

import pytest
from task.src import task_log


class FakeRequest:
    def __init__(self, task_id="abc-123"):
        self.id = task_id


class FakeTask:
    def __init__(self, name="download_pending", task_id="abc-123"):
        self.name = name
        self.request = FakeRequest(task_id)


@pytest.fixture
def written(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        task_log, "write_log", lambda **kwargs: calls.append(kwargs)
    )
    return calls


class TestLogTaskEvent:
    def test_fills_in_the_task_identity(self, written):
        task_log.log_task_event(FakeTask(), "completed", "downloaded 3")
        entry = written[0]
        assert entry["source"] == "notification"
        assert entry["message"] == "downloaded 3"
        assert entry["event"] == "completed"
        assert entry["task_id"] == "abc-123"
        assert entry["task_name"] == "download_pending"
        assert entry["task_title"] == "Downloading"
        assert entry["group"] == "download:run"

    def test_maps_the_event_to_a_level(self, written):
        task_log.log_task_event(FakeTask(), "completed", "fine")
        task_log.log_task_event(FakeTask(), "failed", "boom")
        task_log.log_task_event(FakeTask(), "notify_failed", "no route")
        assert [i["level"] for i in written] == ["info", "error", "error"]

    def test_an_unknown_event_is_info(self, written):
        task_log.log_task_event(FakeTask(), "something_new", "hello")
        assert written[0]["level"] == "info"

    def test_survives_a_task_missing_from_task_config(self, written):
        task_log.log_task_event(FakeTask(name="not_registered"), "failed", "x")
        entry = written[0]
        assert entry["task_name"] == "not_registered"
        assert entry["task_title"] is None
        assert entry["group"] is None

    def test_never_raises(self, monkeypatch):
        def explode(**kwargs):
            raise ValueError("es is down")

        monkeypatch.setattr(task_log, "write_log", explode)
        task_log.log_task_event(FakeTask(), "completed", "downloaded 3")
