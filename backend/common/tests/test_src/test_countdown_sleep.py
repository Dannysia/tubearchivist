"""the paced waits every long running queue sits in

each of these loops notifies at the top of a pass and slept at the
bottom, so the wait was spent showing the item that had just finished.
the countdown is what the user sees instead.
"""

from types import SimpleNamespace

import pytest
from common.src import helper
from common.src.helper import countdown_sleep

CONFIG = {"downloads": {"sleep_interval": 10}}


@pytest.fixture
def clock(monkeypatch):
    """record sleeps instead of taking them"""
    slept: list[int] = []
    monkeypatch.setattr(helper, "sleep", slept.append)
    return slept


@pytest.fixture
def running():
    """a task nobody has stopped"""
    return SimpleNamespace(is_stopped=lambda: False)


def set_interval(monkeypatch, secs):
    """pin the randomised duration"""
    monkeypatch.setattr(helper, "rand_sleep_secs", lambda config: secs)


class TestCountdownSleep:
    """common.src.helper.countdown_sleep"""

    def test_counts_the_wait_down(self, monkeypatch, clock, running):
        seen: list[str] = []
        set_interval(monkeypatch, 3)

        assert countdown_sleep(CONFIG, running, seen.append, "download")

        assert seen == [
            "Waiting 3s before download",
            "Waiting 2s before download",
            "Waiting 1s before download",
        ]
        assert sum(clock) == 3

    def test_label_names_what_is_waited_for(self, monkeypatch, clock, running):
        """each queue waits before a different thing"""
        seen: list[str] = []
        set_interval(monkeypatch, 1)

        countdown_sleep(CONFIG, running, seen.append, "next URL")

        assert seen == ["Waiting 1s before next URL"]

    def test_waits_the_full_interval(self, monkeypatch, clock, running):
        """stepping through it must not shorten or extend the wait"""
        set_interval(monkeypatch, 14)

        countdown_sleep(CONFIG, running, lambda msg: None, "download")

        assert sum(clock) == 14

    def test_says_nothing_when_sleep_is_off(self, monkeypatch, clock, running):
        """sleep_interval unset, the queue runs straight through"""
        seen: list[str] = []
        set_interval(monkeypatch, 0)

        assert countdown_sleep(CONFIG, running, seen.append, "download")

        assert seen == []
        assert clock == []

    def test_stop_cuts_the_wait_short(self, monkeypatch, clock):
        """without this a stop waits out the rest of the interval"""
        seen: list[str] = []
        set_interval(monkeypatch, 30)
        checks = iter([False, False, True])
        task = SimpleNamespace(is_stopped=lambda: next(checks))

        assert not countdown_sleep(CONFIG, task, seen.append, "download")

        assert seen == [
            "Waiting 30s before download",
            "Waiting 29s before download",
        ]
        assert sum(clock) == 2

    def test_stop_before_the_first_step_says_nothing(self, monkeypatch, clock):
        """already stopped, so there is no wait to report"""
        seen: list[str] = []
        set_interval(monkeypatch, 10)
        task = SimpleNamespace(is_stopped=lambda: True)

        assert not countdown_sleep(CONFIG, task, seen.append, "download")

        assert seen == []
        assert clock == []

    def test_sleeps_plainly_without_a_task(self, monkeypatch, clock):
        """nothing to report progress to, so no per second wake up"""
        seen: list[str] = []
        set_interval(monkeypatch, 7)

        assert countdown_sleep(CONFIG, None, seen.append, "download")

        assert seen == []
        assert clock == [7]
