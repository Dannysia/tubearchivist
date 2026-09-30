"""test that an orphan sidecar is reported wherever it sorts"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.src.manual import ImportFolderScanner

DIR = "/cache/import"


@pytest.mark.parametrize(
    "orphan", ["aaaaaaaaaaa.info.json", "zzzzzzzzzzz.info.json"]
)
def test_the_orphan_group_is_kept(orphan):
    files = sorted(
        [
            f"{DIR}/mmmmmmmmmmm.mp4",
            f"{DIR}/mmmmmmmmmmm.info.json",
            f"{DIR}/{orphan}",
        ]
    )
    scanner = ImportFolderScanner.__new__(ImportFolderScanner)

    scanner.match_files(files)

    orphans = [i for i in scanner.to_import if not i["media"]]
    assert [i["metadata"] for i in orphans] == [f"{DIR}/{orphan}"]


def test_an_empty_folder_imports_nothing():
    scanner = ImportFolderScanner.__new__(ImportFolderScanner)

    scanner.match_files([])

    assert scanner.to_import == []
