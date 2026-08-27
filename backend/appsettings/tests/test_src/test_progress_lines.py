"""the progress lines the paced loops in appsettings send

countdown_sleep hands back only the countdown line. each loop appends
it below what it is working on, so the wait reads as the status of that
item instead of replacing it.
"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.src.manual import ImportFolderScanner
from appsettings.src.reindex import Reindex


@pytest.fixture
def sent():
    """capture what reaches the task"""
    captured = []

    def send_progress(message, progress=False):
        captured.append((message, progress))

    return captured, SimpleNamespace(send_progress=send_progress)


class TestReindexNotify:
    """Reindex._notify"""

    def test_plain_line_while_working(self, sent):
        captured, task = sent
        Reindex._notify(SimpleNamespace(task=task), "video", 1445, 412)

        assert captured == [(["Reindexing Videos 412/1445"], 412 / 1445)]

    def test_countdown_goes_under_the_counter(self, sent):
        """the counter has to stay put while the wait ticks"""
        captured, task = sent
        Reindex._notify(
            SimpleNamespace(task=task),
            "video",
            1445,
            412,
            waiting="Waiting 8s before next video",
        )

        message, progress = captured[0]
        assert message == [
            "Reindexing Videos 412/1445",
            "Waiting 8s before next video",
        ]
        assert progress == 412 / 1445


class TestManualImportNotify:
    """ImportFolderScanner._notify"""

    @staticmethod
    def _scanner(task):
        return SimpleNamespace(task=task, to_import=[1, 2, 3, 4])

    def test_plain_lines_while_working(self, sent):
        captured, task = sent
        video = {"media": "/youtube/some/clip.mp4"}
        ImportFolderScanner._notify(self._scanner(task), 1, video)

        assert captured == [
            (["Import queue processing video 2/4", "clip.mp4"], 0.5)
        ]

    def test_countdown_goes_under_the_filename(self, sent):
        captured, task = sent
        video = {"media": "/youtube/some/clip.mp4"}
        ImportFolderScanner._notify(
            self._scanner(task),
            1,
            video,
            waiting="Waiting 8s before next video",
        )

        message, _ = captured[0]
        assert message == [
            "Import queue processing video 2/4",
            "clip.mp4",
            "Waiting 8s before next video",
        ]

    def test_long_filename_still_truncates(self, sent):
        """the countdown must not cost the existing trim"""
        captured, task = sent
        video = {"media": "/youtube/" + "n" * 80 + ".mp4"}
        ImportFolderScanner._notify(
            self._scanner(task), 0, video, waiting="Waiting 1s before x"
        )

        message, _ = captured[0]
        assert message[1] == "n" * 50 + "..."
        assert message[2] == "Waiting 1s before x"


class TestReindexStopPropagates:
    """a stop has to leave reindex_all, not just the current index

    breaking only the inner loop starts the next index type, which is a
    fresh run of youtube requests - the thing stopping is meant to end.
    """

    def test_reindex_type_reports_the_stop(self, monkeypatch):
        from appsettings.src import reindex as reindex_mod

        monkeypatch.setattr(
            reindex_mod, "countdown_sleep", lambda *a, **kw: False
        )
        monkeypatch.setattr(
            reindex_mod, "RedisQueue", lambda name: _queue_of_one()
        )

        instance = _reindex_instance()
        assert (
            reindex_mod.Reindex.reindex_type(
                instance,
                "video",
                {"queue_name": "q", "index_name": "ta_video"},
            )
            is False
        )

    def test_reindex_all_stops_at_the_first_refusal(self, monkeypatch):
        from appsettings.src import reindex as reindex_mod

        started = []

        monkeypatch.setattr(
            reindex_mod,
            "RedisQueue",
            lambda name: SimpleNamespace(length=lambda: 5),
        )

        instance = _reindex_instance()
        instance.cookie_is_valid = lambda: True
        # every type has a full queue, so only the refusal stops it
        instance.reindex_type = (
            lambda name, index_config: started.append(name) or False
        )
        reindex_mod.Reindex.reindex_all(instance)

        assert started == ["video"], "later index types must not start"


def _queue_of_one():
    """a queue holding one item, then empty"""
    items = iter([("abc", 1), (None, None)])
    return SimpleNamespace(
        key="q", max_score=lambda: 1, get_next=lambda: next(items)
    )


def _reindex_instance():
    """enough of a Reindex for the loop, no ES or redis"""
    return SimpleNamespace(
        task=None,
        config={"downloads": {"sleep_interval": 10}},
        REINDEX_CONFIG={
            "video": {"queue_name": "qv", "index_name": "ta_video"},
            "channel": {"queue_name": "qc", "index_name": "ta_channel"},
            "playlist": {"queue_name": "qp", "index_name": "ta_playlist"},
        },
        _notify=lambda *a, **kw: None,
        _mark_active=lambda *a, **kw: None,
        _clear_active=lambda *a, **kw: None,
        reindex_single_video=lambda vid: None,
        _reindex_video_related=lambda video: None,
    )
