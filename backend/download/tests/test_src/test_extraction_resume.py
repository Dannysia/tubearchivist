"""test starting the extraction queue on retry and at startup"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from config.management.commands import ta_startup
from download import views
from download.src import extraction_queue
from download.src.extraction_queue import ExtractionQueue


class Delay:
    def __init__(self):
        self.calls = 0

    def delay(self):
        self.calls += 1


def _search(monkeypatch, response):
    class Wrap:
        def __init__(self, path):
            pass

        def get(self, data=None):
            return response, 200

    monkeypatch.setattr(extraction_queue, "ElasticWrap", Wrap)


@pytest.mark.parametrize(
    "response, expected",
    [
        ({"hits": {"total": {"value": 3}}}, True),
        ({"hits": {"total": {"value": 0}}}, False),
        ({"error": "index_not_found_exception"}, False),
    ],
)
def test_has_work(monkeypatch, response, expected):
    _search(monkeypatch, response)

    assert ExtractionQueue.has_work() is expected


def test_retry_failed_starts_a_run(monkeypatch):
    task = Delay()
    monkeypatch.setattr(views, "process_extraction_queue", task)
    monkeypatch.setattr(
        views.ExtractionInteract, "update_bulk", lambda self, **kwargs: None
    )
    request = SimpleNamespace(
        data={"status": "clear_error"}, query_params={"filter": "failed"}
    )

    response = views.ExtractionApiListView().patch(request)

    assert response.status_code == 204
    assert task.calls == 1


@pytest.mark.parametrize("waiting, runs", [(True, 1), (False, 0)])
def test_startup_resumes_a_waiting_queue(monkeypatch, waiting, runs):
    task = Delay()
    monkeypatch.setattr(ta_startup, "process_extraction_queue", task)
    monkeypatch.setattr(
        ta_startup.ExtractionQueue,
        "has_work",
        classmethod(lambda cls: waiting),
    )

    ta_startup.Command()._resume_extraction_queue()

    assert task.calls == runs
