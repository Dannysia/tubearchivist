"""test the downscale filter counts"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from downscale.src.constants import size_change_clause
from downscale.views import DownscaleAggsApiView

FILTERS = {"channel": "UC1", "encoder": "av1_nvenc", "status": "failed"}


def _query(monkeypatch, field, extra=None):
    view = DownscaleAggsApiView()
    view.data = {}

    def get_aggs(self):
        self.response = {
            key: {
                "buckets": [],
                "sum_other_doc_count": 0,
                "doc_count_error_upper_bound": 0,
            }
            for key in self.data["aggs"]
        }

    monkeypatch.setattr(DownscaleAggsApiView, "get_aggs", get_aggs)
    params = {**FILTERS, **(extra or {}), "field": field}
    view.get(SimpleNamespace(query_params=params))
    return view.data["query"]["bool"]["must"]


@pytest.mark.parametrize(
    "field, own", [("channel", "channel_id"), ("encoder", "encoder")]
)
def test_a_count_applies_every_filter_but_its_own(monkeypatch, field, own):
    must = _query(monkeypatch, field)
    fields = {
        next(iter(clause["term"])) for clause in must if "term" in clause
    }

    assert own not in fields
    assert "status" in fields
    assert {"channel_id", "encoder"} - {own} <= fields


def test_the_saved_count_ignores_the_size_filter(monkeypatch):
    must = _query(monkeypatch, "saved", {"size_change": "larger"})

    assert size_change_clause("larger") not in must
    assert len(must) == len(FILTERS)
