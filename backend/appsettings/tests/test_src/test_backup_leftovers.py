"""test that a backup starts from a clean backup folder"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from appsettings.src.backup import ElasticBackup


def test_leftover_exports_are_cleared_and_archives_kept(tmp_path, monkeypatch):
    for name in ["es_video-20260930-0.json", "es_history-20260930-3.json"]:
        (tmp_path / name).write_text("stale")
    (tmp_path / "ta_backup-20260929-auto.zip").write_text("archive")
    monkeypatch.setattr(ElasticBackup, "BACKUP_DIR", str(tmp_path))

    ElasticBackup.__new__(ElasticBackup)._clear_leftovers()

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "ta_backup-20260929-auto.zip"
    ]
