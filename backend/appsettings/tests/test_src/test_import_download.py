"""test downloading a staged import file"""

# flake8: noqa: E402

import asyncio
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from appsettings import views
from appsettings.src.manual import ImportFolderFiles
from rest_framework.test import APIRequestFactory, force_authenticate
from user.models import Account

VIDEO_ID = "dQw4w9WgXcQ"


def _download(file_name, headers=None):
    request = APIRequestFactory().get(
        f"/api/appsettings/import-file/{file_name}/", headers=headers or {}
    )
    force_authenticate(request, user=Account(name="test", is_staff=True))
    view = views.ImportFileItemView.as_view()
    return view(request, filename=file_name)


async def _collect(response):
    return b"".join([part async for part in response])


def test_download_streams_without_buffering(tmp_path, monkeypatch):
    monkeypatch.setattr(ImportFolderFiles, "IMPORT_DIR", str(tmp_path))
    (tmp_path / f"{VIDEO_ID}.mp4").write_bytes(b"0123456789")

    response = _download(f"{VIDEO_ID}.mp4")

    assert response.status_code == 200
    assert response.is_async
    assert response["Content-Type"] == "video/mp4"
    assert response["Content-Disposition"] == (
        f'attachment; filename="{VIDEO_ID}.mp4"'
    )
    assert response["Content-Length"] == "10"
    assert asyncio.run(_collect(response)) == b"0123456789"


def test_download_serves_a_range(tmp_path, monkeypatch):
    monkeypatch.setattr(ImportFolderFiles, "IMPORT_DIR", str(tmp_path))
    (tmp_path / f"{VIDEO_ID}.mp4").write_bytes(b"0123456789")

    response = _download(f"{VIDEO_ID}.mp4", {"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert asyncio.run(_collect(response)) == b"2345"


def test_download_missing_file_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(ImportFolderFiles, "IMPORT_DIR", str(tmp_path))

    assert _download(f"{VIDEO_ID}.mp4").status_code == 404
