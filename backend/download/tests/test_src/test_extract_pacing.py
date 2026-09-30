"""the per video wait, not parse_url_list's once per queue entry"""

# pylint: disable=protected-access

from types import SimpleNamespace

import pytest
from download.src import queue as queue_mod
from download.src.queue import PendingList


def capture_task():
    """returns (the message lines sent, the task)"""
    sent = []
    task = SimpleNamespace(
        is_stopped=lambda: False,
        send_progress=lambda message_lines, progress=False: sent.append(
            message_lines
        ),
    )
    return sent, task


class TestPace:
    def test_counts_down_when_there_is_a_line_for_it(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            queue_mod,
            "countdown_sleep",
            lambda config, task, notify, label: seen.append(label) or True,
        )

        handler = SimpleNamespace(
            config={}, task=object(), _pace=PendingList._pace
        )
        PendingList._pace(handler, lambda msg: None)

        assert seen == ["next video"]

    def test_waits_stoppably_with_nothing_to_narrate(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            queue_mod,
            "countdown_sleep",
            lambda config, task, notify, label: seen.append(notify) or True,
        )

        handler = SimpleNamespace(config={}, task=object())
        PendingList._pace(handler, None)

        assert seen == [None], "the wait must be taken, just not narrated"


class TestPaceNotify:
    def test_countdown_goes_under_the_item_counter(self):
        sent, task = capture_task()
        handler = SimpleNamespace(task=task, flat=False)
        handler._notify_add = lambda **kw: PendingList._notify_add(
            handler, **kw
        )

        notify = PendingList._pace_notify(
            handler, "channel", "Some Channel", 12, 300
        )
        notify("Waiting 8s before next video")

        assert sent == [
            [
                "Full extracting Channel: 'Some Channel'",
                "Parsing item 12/300.",
                "Waiting 8s before next video",
            ]
        ]

    def test_no_task_means_no_callback(self):
        handler = SimpleNamespace(task=None, flat=False)
        assert PendingList._pace_notify(handler, "channel", "x", 1, 2) is None

    def test_the_last_video_names_no_next_one(self):
        _, task = capture_task()
        handler = SimpleNamespace(task=task, flat=False)

        assert (
            PendingList._pace_notify(handler, "channel", "x", 300, 300) is None
        ), "no next video to count down to"
        assert (
            PendingList._pace_notify(handler, "channel", "x", 299, 300)
            is not None
        ), "but there is one at 299/300"


class TestNotifyAdd:
    @pytest.mark.parametrize("flat", [True, False])
    def test_plain_lines_unchanged(self, flat):
        sent, task = capture_task()
        handler = SimpleNamespace(task=task, flat=flat)

        PendingList._notify_add(handler, "channel", "Some Channel", 3, 10)

        assert len(sent[0]) == 2, "no waiting line when none is passed"
        assert "3/10" in sent[0][1]


class TestParseUrlListTail:
    @staticmethod
    def _handler(task):
        handler = SimpleNamespace(
            config={},
            task=task,
            youtube_ids=[{"type": "video", "url": "a", "vid_type": None}],
            all_pending=[],
            all_videos=[],
            all_channels=[],
            missing_videos=[],
            added=0,
            _notify=lambda *a, **kw: None,
            _process_entry=lambda *a: None,
        )
        handler._wait_for_next = lambda *a: PendingList._wait_for_next(
            handler, *a
        )

        return handler

    def test_single_url_waits_without_narrating(self, monkeypatch):
        waits = []
        monkeypatch.setattr(
            queue_mod,
            "countdown_sleep",
            lambda config, task, notify=None, label="": waits.append(label)
            or True,
        )

        _, task = capture_task()
        handler = self._handler(task)
        PendingList.parse_url_list(handler)

        assert waits == [""], "the wait happens, with no next url named"
