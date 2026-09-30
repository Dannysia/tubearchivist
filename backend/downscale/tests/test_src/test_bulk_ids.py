"""test the downscale bulk action endpoint's id handling"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

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
        lambda doc_id: SimpleNamespace(reject=lambda: acted.append(doc_id)),
    )
    request = SimpleNamespace(data={"action": "reject"})

    DownscaleApiListView().post(request)

    assert acted == ["one", "two"]
