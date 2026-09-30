"""the progress lines the paced loops in appsettings send"""

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
    captured = []

    def send_progress(message, progress=False):
        captured.append((message, progress))

    return captured, SimpleNamespace(send_progress=send_progress)


class TestReindexNotify:
    def test_plain_line_while_working(self, sent):
        captured, task = sent
        Reindex._notify(SimpleNamespace(task=task), "video", 1445, 412)

        assert captured == [(["Reindexing Videos 412/1445"], 412 / 1445)]

    def test_countdown_goes_under_the_counter(self, sent):
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
        captured, task = sent
        video = {"media": "/youtube/" + "n" * 80 + ".mp4"}
        ImportFolderScanner._notify(
            self._scanner(task), 0, video, waiting="Waiting 1s before x"
        )

        message, _ = captured[0]
        assert message[1] == "n" * 50 + "..."
        assert message[2] == "Waiting 1s before x"


class TestReindexStopPropagates:
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

    def test_reindex_type_stops_popping_the_queue(self, monkeypatch):
        from appsettings.src import reindex as reindex_mod

        popped = []

        def get_next():
            popped.append(len(popped) + 1)
            assert len(popped) < 50, "loop did not break on the refusal"
            return f"id{len(popped)}", len(popped)

        monkeypatch.setattr(
            reindex_mod, "countdown_sleep", lambda *a, **kw: False
        )
        monkeypatch.setattr(
            reindex_mod,
            "RedisQueue",
            lambda name: SimpleNamespace(
                key="q",
                max_score=lambda: 99,
                get_next=get_next,
                length=lambda: 99,
            ),
        )

        instance = _reindex_instance()
        assert not reindex_mod.Reindex.reindex_type(
            instance, "video", {"queue_name": "q", "index_name": "ta_video"}
        )
        assert len(popped) == 1, "one item, then out"

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
        instance.reindex_type = (
            lambda name, index_config: started.append(name) or False
        )
        reindex_mod.Reindex.reindex_all(instance)

        assert started == ["video"], "later index types must not start"


def _queue_of_one(length=1):
    items = iter([("abc", 1), (None, None)])
    return SimpleNamespace(
        key="q",
        max_score=lambda: 1,
        get_next=lambda: next(items),
        length=lambda: length,
    )


def _reindex_instance():
    instance = SimpleNamespace(
        task=SimpleNamespace(is_stopped=lambda: False),
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
    instance._wait_for_next = lambda *a: Reindex._wait_for_next(instance, *a)

    return instance


class TestReindexTrailingWait:
    def test_drained_queue_waits_without_narrating(self, monkeypatch):
        from appsettings.src import reindex as reindex_mod

        waits = []
        monkeypatch.setattr(
            reindex_mod,
            "countdown_sleep",
            lambda config, task, notify=None, label="": waits.append(
                (notify, label)
            )
            or True,
        )
        monkeypatch.setattr(
            reindex_mod, "RedisQueue", lambda name: _queue_of_one(length=0)
        )

        instance = _reindex_instance()
        assert reindex_mod.Reindex.reindex_type(
            instance, "video", {"queue_name": "q", "index_name": "ta_video"}
        )

        assert waits == [(None, "")], "the wait happens, unnarrated"

    def test_a_stop_in_the_drained_wait_leaves_the_whole_run(
        self, monkeypatch
    ):
        from appsettings.src import reindex as reindex_mod

        monkeypatch.setattr(
            reindex_mod,
            "countdown_sleep",
            lambda config, task, notify=None, label="": False,
        )
        monkeypatch.setattr(
            reindex_mod, "RedisQueue", lambda name: _queue_of_one(length=0)
        )

        instance = _reindex_instance()

        assert not reindex_mod.Reindex.reindex_type(
            instance, "video", {"queue_name": "q", "index_name": "ta_video"}
        )

    def test_more_in_the_queue_counts_down(self, monkeypatch):
        from appsettings.src import reindex as reindex_mod

        counted = []
        monkeypatch.setattr(
            reindex_mod,
            "countdown_sleep",
            lambda *a, **kw: counted.append(kw.get("label")) or True,
        )
        monkeypatch.setattr(
            reindex_mod, "RedisQueue", lambda name: _queue_of_one(length=4)
        )

        instance = _reindex_instance()
        reindex_mod.Reindex.reindex_type(
            instance, "video", {"queue_name": "q", "index_name": "ta_video"}
        )

        assert counted == ["next video"]
