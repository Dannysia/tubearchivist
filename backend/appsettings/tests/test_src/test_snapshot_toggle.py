"""test what toggling snapshots does to the snapshots already taken"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.src import config, snapshot
from appsettings.src.config import AppConfig
from config.management.commands import ta_startup


class FakeElasticWrap:
    calls: list[tuple[str, str]] = []

    def __init__(self, path):
        self.path = path

    def get(self, *args, **kwargs):
        self.calls.append(("get", self.path))
        return {}, 200

    def delete(self, *args, **kwargs):
        self.calls.append(("delete", self.path))
        return {}, 200


def test_disabling_keeps_existing_snapshots(monkeypatch):
    FakeElasticWrap.calls = []
    monkeypatch.setattr(snapshot, "ElasticWrap", FakeElasticWrap)
    monkeypatch.setattr(snapshot, "get_mapping", lambda: [])
    handler = AppConfig.__new__(AppConfig)

    handler.post_process_updated({"application": {"enable_snapshot": False}})

    deletes = [
        path for verb, path in FakeElasticWrap.calls if verb == "delete"
    ]
    assert deletes == ["_slm/policy/ta_daily"]


def test_other_settings_leave_snapshots_alone(monkeypatch):
    called = []
    monkeypatch.setattr(config, "ElasticSnapshot", lambda: called.append(1))
    handler = AppConfig.__new__(AppConfig)

    handler.post_process_updated({"application": {"enable_cast": True}})

    assert not called


class FakeSnapshot:
    calls: list[str] = []

    def setup(self):
        self.calls.append("setup")

    def delete_policy(self):
        self.calls.append("delete_policy")


@pytest.mark.parametrize(
    "is_enabled, expected", [(True, ["setup"]), (False, ["delete_policy"])]
)
def test_startup_follows_the_setting(monkeypatch, is_enabled, expected):
    FakeSnapshot.calls = []
    monkeypatch.setattr(ta_startup, "ElasticSnapshot", FakeSnapshot)
    monkeypatch.setattr(
        ta_startup,
        "AppConfig",
        lambda: SimpleNamespace(
            config={"application": {"enable_snapshot": is_enabled}}
        ),
    )

    ta_startup.Command()._snapshot_check()

    assert FakeSnapshot.calls == expected
