"""test the downscale bulk action endpoint's id handling"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from downscale import views
from downscale.views import DownscaleApiListView


def test_an_empty_id_list_acts_on_nothing(monkeypatch):
    acted = []
    monkeypatch.setattr(
        DownscaleApiListView,
        "_get_ids_by_filter",
        staticmethod(lambda request: ["every", "job"]),
    )
    monkeypatch.setattr(
        views,
        "DownscaleReview",
        lambda doc_id: SimpleNamespace(reject=lambda: acted.append(doc_id)),
    )
    request = SimpleNamespace(data={"action": "reject", "ids": []})

    response = DownscaleApiListView().post(request)

    assert acted == []
    assert response.data == {"success": [], "failed": []}


def test_no_id_list_acts_on_the_filter(monkeypatch):
    acted = []
    monkeypatch.setattr(
        DownscaleApiListView,
        "_get_ids_by_filter",
        staticmethod(lambda request: ["one", "two"]),
    )
    monkeypatch.setattr(
        views,
        "DownscaleReview",
        lambda doc_id: SimpleNamespace(cancel=lambda: acted.append(doc_id)),
    )
    request = SimpleNamespace(data={"action": "cancel"})

    DownscaleApiListView().post(request)

    assert acted == ["one", "two"]


def test_accept_by_filter_is_queued(monkeypatch):
    queued = []
    monkeypatch.setattr(
        DownscaleApiListView,
        "_get_ids_by_filter",
        staticmethod(lambda request: ["one", "two"]),
    )
    monkeypatch.setattr(views, "get_active_bulk", lambda: None)
    monkeypatch.setattr(
        views,
        "queue_bulk",
        lambda ids, action: queued.append((ids, action))
        or {
            "task_id": "task1",
            "action": action,
            "total": len(ids),
            "done": 0,
            "failed": [],
            "status": "queued",
            "stopped": False,
            "failure": None,
        },
    )
    request = SimpleNamespace(data={"action": "accept"})

    response = DownscaleApiListView().post(request)

    assert response.status_code == 202
    assert queued == [(["one", "two"], "accept")]
    assert response.data["task_id"] == "task1"


def test_a_second_bulk_accept_is_refused(monkeypatch):
    monkeypatch.setattr(
        views, "get_active_bulk", lambda: {"task_id": "running"}
    )
    monkeypatch.setattr(
        views,
        "queue_bulk",
        lambda ids, action: pytest.fail("must not queue"),
    )
    request = SimpleNamespace(data={"action": "reject", "ids": ["one", "two"]})

    response = DownscaleApiListView().post(request)

    assert response.status_code == 409


def test_a_single_job_is_accepted_inline_even_during_a_bulk(monkeypatch):
    acted = []
    monkeypatch.setattr(
        views, "get_active_bulk", lambda: {"task_id": "running"}
    )
    monkeypatch.setattr(
        views,
        "DownscaleReview",
        lambda doc_id: SimpleNamespace(accept=lambda: acted.append(doc_id)),
    )
    request = SimpleNamespace(data={"action": "accept", "ids": ["one"]})

    response = DownscaleApiListView().post(request)

    assert acted == ["one"]
    assert response.data == {"success": ["one"], "failed": []}
