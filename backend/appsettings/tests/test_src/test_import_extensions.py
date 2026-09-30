"""test that manual import treats file extensions case-insensitively"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.src import manual
from appsettings.src.manual import ImportFolderScanner


@pytest.fixture
def scanner(monkeypatch):
    calls = {"run": [], "remove": []}
    monkeypatch.setattr(
        manual.subprocess, "run", lambda *a, **k: calls["run"].append(a)
    )
    monkeypatch.setattr(
        manual.os, "remove", lambda path: calls["remove"].append(path)
    )
    instance = ImportFolderScanner.__new__(ImportFolderScanner)
    instance.calls = calls
    return instance


@pytest.mark.parametrize("name", ["abc.mp4", "abc.MP4", "abc.Mp4"])
def test_an_mp4_is_never_converted(scanner, name):
    video = {"media": f"/cache/import/{name}"}

    scanner._convert_video(video)

    assert scanner.calls == {"run": [], "remove": []}
    assert video["media"] == f"/cache/import/{name}"


def test_an_uppercase_mp4_gets_its_embedded_thumb(scanner, monkeypatch):
    monkeypatch.setattr(
        ImportFolderScanner, "get_mp4_thumb_type", lambda self, path: "jpg"
    )
    monkeypatch.setattr(
        ImportFolderScanner,
        "dump_mp4_thumb",
        staticmethod(lambda path, thumb_type: "/cache/import/abc.jpg"),
    )
    video = {"media": "/cache/import/abc.MP4", "thumb": False}

    scanner._dump_thumb(video)

    assert video["thumb"] == "/cache/import/abc.jpg"
