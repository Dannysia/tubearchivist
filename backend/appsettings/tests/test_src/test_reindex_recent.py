# flake8: noqa: E402

import os
from datetime import datetime
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.src import reindex
from appsettings.src.reindex import ReindexPopulate

NOW = int(datetime(2026, 10, 23, 12, 0).timestamp())


@pytest.fixture(name="populate")
def fixture_populate(monkeypatch):
    monkeypatch.setattr(
        reindex, "AppConfig", lambda: SimpleNamespace(config={})
    )
    populate = ReindexPopulate()
    populate.now = NOW
    populate.queries = []
    populate.queued = []

    def search(path):
        def get(data):
            populate.queries.append(data)
            hits = [{"_source": {"youtube_id": "recent00001"}}]
            return {"hits": {"hits": hits}}, 200

        return SimpleNamespace(get=get)

    monkeypatch.setattr(reindex, "ElasticWrap", search)
    monkeypatch.setattr(
        populate, "populate", lambda ids, config: populate.queued.extend(ids)
    )
    return populate


def _task_config(monkeypatch, task_config):
    monkeypatch.setattr(
        reindex.CustomPeriodicTask.objects,
        "get",
        lambda name: SimpleNamespace(task_config=task_config),
    )


def _published_since(populate):
    must = populate.queries[0]["query"]["bool"]["must"]
    return next(m["range"]["published"]["gte"] for m in must if "range" in m)


def test_recent_videos_default_to_the_first_week(populate):
    populate.add_recent()

    assert _published_since(populate) == "2026-10-16"
    assert populate.queued == ["recent00001"]


def test_recent_days_comes_from_the_reindex_task(populate, monkeypatch):
    _task_config(monkeypatch, {"days": 90, "recent_days": 3})

    populate.get_config()
    populate.add_recent()

    assert populate.interval == 90
    assert _published_since(populate) == "2026-10-20"


def test_zero_recent_days_turns_it_off(populate, monkeypatch):
    _task_config(monkeypatch, {"recent_days": 0})

    populate.get_config()
    populate.add_recent()

    assert populate.queries == []
    assert populate.queued == []


def test_a_task_without_recent_days_keeps_the_default(populate, monkeypatch):
    _task_config(monkeypatch, {"days": 60})

    populate.get_config()

    assert populate.interval == 60
    assert populate.recent_days == 7
