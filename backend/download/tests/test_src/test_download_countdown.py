"""the wait between two downloads, as the progress message sees it

the sleep sits between the archive message of one video and the first
message of the next, so anything it fails to write leaves the finished
video's message on screen for the whole interval.
"""

from types import SimpleNamespace

import pytest
from download.src import yt_dlp_handler
from download.src.yt_dlp_handler import VideoDownloader

VIDEO = {"youtube_id": "abc", "vid_type": "videos", "title": "some video"}


@pytest.fixture
def recorder(monkeypatch):
    """a downloader that records instead of sleeping"""
    slept: list[int] = []
    notified: list[str] = []
    monkeypatch.setattr(yt_dlp_handler, "sleep", slept.append)

    fake = SimpleNamespace(
        config={"downloads": {"sleep_interval": 10}},
        COUNTDOWN_STEP=VideoDownloader.COUNTDOWN_STEP,
        task=SimpleNamespace(is_stopped=lambda: False),
        _notify=lambda video_data, message: notified.append(message),
    )
    return fake, slept, notified


def set_interval(monkeypatch, secs):
    """pin the randomised duration"""
    monkeypatch.setattr(yt_dlp_handler, "rand_sleep_secs", lambda config: secs)


class TestSleepBetween:
    """VideoDownloader._sleep_between"""

    def test_counts_the_wait_down(self, monkeypatch, recorder):
        fake, slept, notified = recorder
        set_interval(monkeypatch, 3)

        VideoDownloader._sleep_between(fake, VIDEO)

        assert notified == [
            "Waiting 3s before next video",
            "Waiting 2s before next video",
            "Waiting 1s before next video",
        ]
        assert sum(slept) == 3

    def test_waits_the_full_interval(self, monkeypatch, recorder):
        """stepping through it must not shorten or extend the wait"""
        fake, slept, _ = recorder
        set_interval(monkeypatch, 14)

        VideoDownloader._sleep_between(fake, VIDEO)

        assert sum(slept) == 14

    def test_says_nothing_when_sleep_is_off(self, monkeypatch, recorder):
        """sleep_interval unset, the queue runs straight through"""
        fake, slept, notified = recorder
        set_interval(monkeypatch, 0)

        VideoDownloader._sleep_between(fake, VIDEO)

        assert notified == []
        assert slept == []

    def test_stop_cuts_the_wait_short(self, monkeypatch, recorder):
        """without this a stop waits out the rest of the interval"""
        fake, slept, notified = recorder
        set_interval(monkeypatch, 30)
        checks = iter([False, False, True])
        fake.task = SimpleNamespace(is_stopped=lambda: next(checks))

        VideoDownloader._sleep_between(fake, VIDEO)

        assert notified == [
            "Waiting 30s before next video",
            "Waiting 29s before next video",
        ]
        assert sum(slept) == 2

    def test_sleeps_plainly_without_a_task(self, monkeypatch, recorder):
        """nothing to report progress to, so no per second wake up"""
        fake, slept, notified = recorder
        set_interval(monkeypatch, 7)
        fake.task = False

        VideoDownloader._sleep_between(fake, VIDEO)

        assert notified == []
        assert slept == [7]
