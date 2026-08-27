"""test which task outcomes reach the log

BaseTask fires its callbacks on every run of every task, so what it
chooses to record is what decides whether the log is readable. These
cover the choice, not the writing, which test_task_log covers.
"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from task import tasks


class FakeRequest:
    """the id celery hangs off a bound task"""

    def __init__(self, task_id="abc-123"):
        self.id = task_id


class StubTask(tasks.BaseTask):
    """a BaseTask with a name and a request, as celery would give it"""

    name = "download_pending"

    def __init__(self, task_id="abc-123"):
        self._fake_request = FakeRequest(task_id)

    @property
    def request(self):
        return self._fake_request


class FakeRedis:
    """the toast writer, which is not what these tests are about"""

    def set_message(self, key, message, expire=False, save=False):
        return None


@pytest.fixture
def logged(monkeypatch):
    """capture log_task_event without touching es or redis"""
    calls: list = []
    monkeypatch.setattr(
        tasks,
        "log_task_event",
        lambda task, event, message, level=None: calls.append(
            (event, message)
        ),
    )
    monkeypatch.setattr(tasks, "RedisArchivist", FakeRedis)
    monkeypatch.setattr(
        tasks,
        "TaskManager",
        lambda: type("M", (), {"get_task": lambda s, i: {}})(),
    )
    return calls


class TestOnSuccess:
    """a task that finished without raising"""

    def test_a_summary_is_logged(self, logged):
        StubTask().on_success("downloaded 3 video(s).", "abc-123", (), {})
        assert logged == [("completed", "downloaded 3 video(s).")]

    def test_nothing_to_do_is_not_logged(self, logged):
        # update_subscribed ticks every five minutes and returns None
        # when it finds nothing. Logging those would bury every real
        # event under hundreds of them
        StubTask().on_success(None, "abc-123", (), {})
        assert logged == []

    def test_an_empty_string_is_not_logged(self, logged):
        StubTask().on_success("", "abc-123", (), {})
        assert logged == []


class TestOnFailure:
    """a task that raised"""

    def test_every_failure_is_logged(self, logged):
        StubTask().on_failure(
            ConnectionError("YouTube bot detection, abort!"),
            "abc-123",
            (),
            {},
            None,
        )
        event, message = logged[0]
        assert event == "failed"
        assert "YouTube bot detection" in message


class TestAfterReturn:
    """the apprise dispatch that follows a task"""

    def _run(self, monkeypatch, result):
        monkeypatch.setattr(
            tasks,
            "Notifications",
            lambda name: type("N", (), {"send": lambda s, i, t: result})(),
        )
        StubTask().after_return("SUCCESS", None, "abc-123", (), {}, None)

    def test_nothing_configured_is_not_logged(self, monkeypatch, logged):
        # the normal state of an install with no apprise urls
        self._run(monkeypatch, None)
        assert logged == []

    def test_a_send_is_logged(self, monkeypatch, logged):
        self._run(monkeypatch, (True, "notification sent to 2 url(s): done"))
        event, message = logged[0]
        assert event == "notified"
        assert "2 url(s)" in message

    def test_a_failed_send_is_logged(self, monkeypatch, logged):
        self._run(monkeypatch, (False, "notification failed for 1 url(s)"))
        assert logged[0][0] == "notify_failed"
