"""test what a filesystem rescan does with a file it cannot index"""

# flake8: noqa: E402

import os
import subprocess

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
import requests
from appsettings.src import filesystem
from appsettings.src.filesystem import Scanner
from common.src.es_connect import ElasticUnavailable
from mutagen import MutagenError
from video.src import index as video_index
from video.src.index import index_new_video

FILE_PATH = "/youtube/UC1/video1.mp4"
VIDEO_ID = "video1"


def _scanner(monkeypatch, raises, ignore_error=True, prefer_local=False):
    scanner = Scanner(ignore_error=ignore_error, prefer_local=prefer_local)
    scanner.notified = []

    def index_new(youtube_id, video_type=None):
        raise raises

    monkeypatch.setattr(filesystem, "index_new_video", index_new)
    monkeypatch.setattr(
        Scanner,
        "_notify_error",
        lambda self, youtube_id: scanner.notified.append(youtube_id),
    )
    monkeypatch.setattr(
        Scanner, "_index_from_embed", lambda self, path, yt_id: False
    )

    return scanner


class TestIndexOneSurvivesTheFile:
    @pytest.mark.parametrize(
        "err",
        [
            ValueError("failed to get metadata"),
            subprocess.CalledProcessError(1, ["ffprobe", FILE_PATH]),
            KeyError("vid_thumb_url"),
            MutagenError("truncated atom"),
            OSError("Input/output error"),
        ],
    )
    def test_ignore_error_holds_for_all_of_them(self, monkeypatch, err):
        scanner = _scanner(monkeypatch, err)

        assert scanner._index_one(FILE_PATH, VIDEO_ID) is True
        assert scanner.notified == [VIDEO_ID]

    def test_without_ignore_error_it_still_stops_the_run(self, monkeypatch):
        scanner = _scanner(
            monkeypatch,
            subprocess.CalledProcessError(1, ["ffprobe", FILE_PATH]),
            ignore_error=False,
        )

        with pytest.raises(subprocess.CalledProcessError):
            scanner._index_one(FILE_PATH, VIDEO_ID)

        assert scanner.notified == []

    def test_the_original_error_reaches_the_task(self, monkeypatch):
        scanner = _scanner(
            monkeypatch, KeyError("vid_thumb_url"), ignore_error=False
        )

        with pytest.raises(KeyError) as err:
            scanner._index_one(FILE_PATH, VIDEO_ID)

        assert "vid_thumb_url" in str(err.value)


class TestEmbedFallbackCannotKillTheScan:
    def test_an_unparsable_file_falls_through_to_youtube(self, monkeypatch):
        reached = []
        scanner = Scanner(ignore_error=True, prefer_local=True)

        monkeypatch.setattr(
            filesystem,
            "index_new_video",
            lambda youtube_id: reached.append(youtube_id),
        )
        monkeypatch.setattr(Scanner, "_cleanup", lambda self, yt_id: None)
        monkeypatch.setattr(
            filesystem, "Comments", lambda *args, **kwargs: _NoComments()
        )
        monkeypatch.setattr(
            filesystem, "YoutubeVideo", lambda yt_id: _NoEmbed()
        )

        def bad_embed(self, path, yt_id):
            raise MutagenError("truncated atom")

        monkeypatch.setattr(Scanner, "_index_from_embed", bad_embed)

        assert scanner._index_one(FILE_PATH, VIDEO_ID) is True
        assert reached == [VIDEO_ID]

    def test_a_failed_fallback_after_youtube_is_reported(self, monkeypatch):
        scanner = Scanner(ignore_error=True)
        scanner.notified = []

        monkeypatch.setattr(
            filesystem,
            "index_new_video",
            lambda youtube_id: (_ for _ in ()).throw(ValueError("no meta")),
        )
        monkeypatch.setattr(
            Scanner,
            "_notify_error",
            lambda self, youtube_id: scanner.notified.append(youtube_id),
        )

        def bad_embed(self, path, yt_id):
            raise MutagenError("truncated atom")

        monkeypatch.setattr(Scanner, "_index_from_embed", bad_embed)

        assert scanner._index_one(FILE_PATH, VIDEO_ID) is True
        assert scanner.notified == [VIDEO_ID]


class _NoComments:
    def build_json(self, upload=False):
        return None


class _NoEmbed:
    def embed_metadata(self):
        return None


class TestIndexNewVideoOnADeactivatedVideo:
    def test_a_reindex_that_deactivated_it_raises_value_error(
        self, monkeypatch
    ):
        class AlreadyIndexed:
            def __init__(self, youtube_id, video_type=None):
                self.youtube_id = youtube_id
                self.json_data = {"youtube_id": youtube_id}

            def get_from_es(self, print_error=True):
                return None

        monkeypatch.setattr(video_index, "YoutubeVideo", AlreadyIndexed)

        import appsettings.src.reindex as reindex_module

        class Deactivating:
            def reindex_single_video(self, youtube_id, is_redownload=False):
                return None

        monkeypatch.setattr(reindex_module, "Reindex", Deactivating)

        with pytest.raises(ValueError) as err:
            index_new_video(VIDEO_ID)

        assert VIDEO_ID in str(err.value)


NETWORK_FAILURES = [
    requests.ConnectionError("connection refused"),
    requests.ReadTimeout("timed out"),
    # what yt-dlp raises on a bot block or a dns failure
    ConnectionError("lost the internet, abort!"),
    ElasticUnavailable("es answered 503, write not applied"),
]


class TestANetworkErrorIsNotABadFile:
    @pytest.mark.parametrize("err", NETWORK_FAILURES)
    def test_it_stops_the_scan(self, monkeypatch, err):
        scanner = _scanner(monkeypatch, err, ignore_error=True)

        with pytest.raises(type(err)):
            scanner._index_one(FILE_PATH, VIDEO_ID)

        assert scanner.notified == []

    @pytest.mark.parametrize("err", NETWORK_FAILURES)
    def test_it_stops_the_scan_from_the_embed_fallback(self, monkeypatch, err):
        scanner = Scanner(ignore_error=True, prefer_local=True)

        def bad_embed(self, path, yt_id):
            raise err

        monkeypatch.setattr(Scanner, "_index_from_embed", bad_embed)

        with pytest.raises(type(err)):
            scanner._index_one(FILE_PATH, VIDEO_ID)
