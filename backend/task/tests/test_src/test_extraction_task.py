"""test what the extraction task does after a run with failures"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from task import tasks


@pytest.fixture
def run(monkeypatch):
    started = []

    class Manager:
        def is_pending(self, task):
            return False

        def init(self, task):
            return None

    monkeypatch.setattr(tasks, "TaskManager", Manager)
    monkeypatch.setattr(
        tasks.download_pending,
        "delay",
        lambda **kwargs: started.append(kwargs),
    )

    def with_result(result, videos_failed=0):
        class Queue:
            def __init__(self, task=None):
                self.videos_failed = videos_failed

            def run_queue(self):
                return result

        monkeypatch.setattr(tasks, "ExtractionQueue", Queue)
        return tasks.process_extraction_queue.run(), started

    return with_result


def test_a_failure_still_starts_the_auto_downloads(run):
    message, started = run((2, 1, True))

    assert started == [{"auto_only": True}]
    assert "1 failed" in message


def test_a_clean_run_reports_what_it_resolved(run):
    message, started = run((3, 0, False))

    assert started == []
    assert message == "resolved 3 extraction item(s)."


def test_videos_that_could_not_be_extracted_are_reported(run):
    message, _ = run((1, 0, False), videos_failed=3)

    assert message == (
        "resolved 1 extraction item(s), 3 videos could not be extracted, "
        "listed as failed in the extraction queue."
    )
