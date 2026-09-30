"""test what a notification send reports"""

import pytest
from task.src import notify
from task.src.notify import Notifications

VALID = "json://localhost/hook"
INVALID = "notaurl://nothing"


class FakeApprise:
    notify_result = True

    def __init__(self):
        self.added = []

    def add(self, url):
        parts = [i.strip() for i in url.split(",")]
        self.added.extend(i for i in parts if i != INVALID)
        return INVALID not in parts

    def __len__(self):
        return len(self.added)

    def notify(self, body, title):
        return FakeApprise.notify_result


@pytest.fixture
def send(monkeypatch):
    FakeApprise.notify_result = True
    monkeypatch.setattr(notify.apprise, "Apprise", FakeApprise)
    monkeypatch.setattr(
        Notifications, "_build_message", lambda self, *a: ("title", "body")
    )

    def run(urls):
        monkeypatch.setattr(Notifications, "get_urls", lambda self: urls)
        return Notifications("task").send("task-1", "Task")

    return run


def test_every_url_valid(send):
    assert send([VALID, VALID]) == (
        True,
        "notification sent to 2 url(s): body",
    )


def test_an_invalid_url_is_not_counted_as_sent(send):
    ok, message = send([VALID, INVALID])

    assert ok is False
    assert "sent to 1 url(s)" in message
    assert "1 rejected as invalid" in message
    assert INVALID not in message


def test_only_invalid_urls_send_nothing(send):
    assert send([INVALID]) == (False, "all 1 notification url(s) are invalid")


def test_a_failed_notify_counts_what_was_accepted(send):
    FakeApprise.notify_result = False

    assert send([VALID, INVALID]) == (
        False,
        "notification failed for 1 url(s)",
    )


def test_an_entry_with_one_bad_url_still_sends_the_rest(send):
    """apprise adds the valid part of an entry and still answers False"""
    ok, message = send([f"{VALID}, {INVALID}"])

    assert ok is False
    assert "sent to 1 url(s)" in message
    assert "1 rejected as invalid" in message
