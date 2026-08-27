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
