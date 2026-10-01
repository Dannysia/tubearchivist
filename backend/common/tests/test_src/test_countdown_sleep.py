"""the paced waits every long running queue sits in"""

from types import SimpleNamespace

import pytest
from common.src import helper
from common.src.helper import countdown_sleep

CONFIG = {"downloads": {"sleep_interval": 10}}


@pytest.fixture
def clock(monkeypatch):
    slept: list[int] = []
    monkeypatch.setattr(helper, "sleep", slept.append)
    return slept


@pytest.fixture
def running():
    return SimpleNamespace(is_stopped=lambda: False)


def set_interval(monkeypatch, secs):
    monkeypatch.setattr(helper, "rand_sleep_secs", lambda config: secs)


class TestCountdownSleep:
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
        seen: list[str] = []
        set_interval(monkeypatch, 1)

        countdown_sleep(CONFIG, running, seen.append, "next URL")

        assert seen == ["Waiting 1s before next URL"]

    def test_waits_the_full_interval(self, monkeypatch, clock, running):
        set_interval(monkeypatch, 14)

        countdown_sleep(CONFIG, running, lambda msg: None, "download")

        assert sum(clock) == 14

    def test_says_nothing_when_sleep_is_off(self, monkeypatch, clock, running):
        seen: list[str] = []
        set_interval(monkeypatch, 0)

        assert countdown_sleep(CONFIG, running, seen.append, "download")

        assert seen == []
        assert clock == []

    def test_stop_cuts_the_wait_short(self, monkeypatch, clock):
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
        seen: list[str] = []
        set_interval(monkeypatch, 10)
        task = SimpleNamespace(is_stopped=lambda: True)

        assert not countdown_sleep(CONFIG, task, seen.append, "download")

        assert seen == []
        assert clock == []

    def test_sleeps_plainly_without_a_task(self, monkeypatch, clock):
        seen: list[str] = []
        set_interval(monkeypatch, 7)

        assert countdown_sleep(CONFIG, None, seen.append, "download")

        assert seen == []
        assert clock == [7]


class TestSilentWait:
    def test_waits_the_full_interval_silently(
        self, monkeypatch, clock, running
    ):
        set_interval(monkeypatch, 7)

        assert countdown_sleep(CONFIG, running)

        assert sum(clock) == 7

    def test_still_stops(self, monkeypatch, clock):
        set_interval(monkeypatch, 30)
        checks = iter([False, True])
        task = SimpleNamespace(is_stopped=lambda: next(checks))

        assert not countdown_sleep(CONFIG, task)

        assert sum(clock) == 1, "stopped after one step, not 30"

    def test_no_task_still_takes_the_wait(self, monkeypatch, clock):
        set_interval(monkeypatch, 9)

        assert countdown_sleep(CONFIG, None)

        assert clock == [9]


class TestPollsEvenWithPacingOff:
    @pytest.mark.parametrize("interval", [None, 0])
    def test_a_stop_is_seen_with_no_wait_to_step_through(
        self, clock, interval
    ):
        config = {"downloads": {"sleep_interval": interval}}
        checks = []
        task = SimpleNamespace(is_stopped=lambda: checks.append(1) or True)

        assert not countdown_sleep(config, task)

        assert len(checks) == 1, "must poll once even with nothing to wait"
        assert clock == [], "and must not invent a wait"

    def test_a_running_task_still_passes_straight_through(
        self, monkeypatch, clock, running
    ):
        set_interval(monkeypatch, 0)

        assert countdown_sleep(CONFIG, running)

        assert clock == []
