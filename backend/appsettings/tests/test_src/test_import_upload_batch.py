"""test an import upload batch that fails part way"""

# flake8: noqa: E402

import errno
import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings import views
from appsettings.views import ImportFileView


@pytest.mark.parametrize(
    "staged_before, rolled_back",
    [(set(), ["first000000.mp4"]), ({"first000000.mp4"}, [])],
)
def test_a_full_disk_rolls_back_the_batch(
    monkeypatch, staged_before, rolled_back
):
    removed = []

    def save(upload):
        if upload.name == "second00000.mp4":
            raise OSError(errno.ENOSPC, "No space left on device")

        return {"filename": upload.name}

    files = views.ImportFolderFiles
    monkeypatch.setattr(files, "save", staticmethod(save))
    monkeypatch.setattr(files, "find_indexed", staticmethod(lambda names: []))
    monkeypatch.setattr(
        files,
        "file_path",
        staticmethod(lambda name: "/x" if name in staged_before else None),
    )
    monkeypatch.setattr(
        files, "delete_file", staticmethod(lambda name: removed.append(name))
    )
    uploads = [
        SimpleNamespace(name="first000000.mp4"),
        SimpleNamespace(name="second00000.mp4"),
    ]
    request = SimpleNamespace(
        FILES=SimpleNamespace(getlist=lambda key: uploads)
    )

    response = ImportFileView().post(request)

    assert response.status_code == 400
    assert "No space left" in response.data["error"]
    assert removed == rolled_back
