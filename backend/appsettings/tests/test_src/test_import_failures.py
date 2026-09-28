"""test how a manual import reports a video it cannot import

YT answers for any well formed eleven character id, so a media file
named with a typo in its id gets the same empty stub a removed video
returns, with no info.json to fall back on.
"""

import subprocess
from types import SimpleNamespace

import pytest
from appsettings.src.manual import ImportFolderScanner, ManualImport

VIDEO_ID = "R6no2zOuCTB"
MEDIA_PATH = f"/cache/import/{VIDEO_ID}.mp4"


def build_current_video(**overwrites):
    """a matched video as match_files hands it over"""
    current_video = {
        "media": MEDIA_PATH,
        "video_id": VIDEO_ID,
        "metadata": False,
        "thumb": False,
        "subtitle": [],
    }
    current_video.update(overwrites)

    return current_video


def build_importer(**overwrites):
    """a ManualImport with no config of its own to read"""
    return ManualImport(
        build_current_video(**overwrites),
        config={},
        ignore_error=False,
        prefer_local=False,
    )


def build_video(answered: bool):
    """a YoutubeVideo as build_json leaves it when it raises

    a stand in, not the real class: constructing one reaches for ES, and
    these two attributes are all the message reads
    """
    return SimpleNamespace(youtube_id=VIDEO_ID, youtube_answered=answered)


class TestWhyNoMetadata:
    def test_names_the_file_not_just_the_id(self):
        """a bulk import reports by file, the id alone is not findable"""
        message = build_importer()._why_no_metadata(
            build_video(answered=False),
            info_json=False,
            err=ValueError("Could not extract published date"),
        )

        assert f"{VIDEO_ID}.mp4" in message

    def test_points_at_a_typo_when_youtube_never_answered(self):
        """the typo and the removed video are indistinguishable here, so
        the message offers both"""
        message = build_importer()._why_no_metadata(
            build_video(answered=False),
            info_json=False,
            err=ValueError("Could not extract published date"),
        )

        assert "typo" in message
        assert "Generate metadata" in message

    def test_says_the_sidecar_came_up_short_when_there_was_one(self):
        """a file was supplied and still did not cover the gap, so the
        remedy is fixing that file, not writing one"""
        message = build_importer(metadata=f"{VIDEO_ID}.info.json")
        message = message._why_no_metadata(
            build_video(answered=False),
            info_json={"id": VIDEO_ID},
            err=ValueError("Could not extract published date"),
        )

        assert "info.json beside the file did not fill the gap" in message
        assert "Could not extract published date" in message
        # writing another one is not the fix when one is already there
        assert "Generate metadata" not in message

    def test_passes_the_original_through_when_youtube_did_answer(self):
        """an age gated video answers in full, so a failure past that is
        some other gap and the underlying message is the useful one"""
        message = build_importer()._why_no_metadata(
            build_video(answered=True),
            info_json=False,
            err=ValueError("got an unexpected redirect"),
        )

        assert "got an unexpected redirect" in message
        assert "typo" not in message


class TestBatchKeepsGoing:
    """one unimportable file must not take the rest of the queue"""

    @staticmethod
    def build_scanner(to_import, failing):
        """a scanner whose per video import fails for named files"""
        scanner = ImportFolderScanner()
        scanner.to_import = to_import
        scanner.imported = []

        def fake_process(current_video, config):
            # pylint: disable=unused-argument
            name = current_video["media"]
            if name in failing:
                raise ValueError(f"{name}: no metadata")

            scanner.imported.append(name)

        scanner._process_video = fake_process

        return scanner

    def test_later_videos_still_import(self, monkeypatch):
        monkeypatch.setattr(
            "appsettings.src.manual.AppConfig",
            lambda: type("C", (), {"config": {}})(),
        )
        monkeypatch.setattr(
            "appsettings.src.manual.countdown_sleep",
            lambda *args, **kwargs: True,
        )
        to_import = [
            {"media": "/cache/import/good_one.mp4"},
            {"media": "/cache/import/bad.mp4"},
            {"media": "/cache/import/good_two.mp4"},
        ]
        scanner = self.build_scanner(to_import, {"/cache/import/bad.mp4"})

        scanner.process_videos()

        assert scanner.imported == [
            "/cache/import/good_one.mp4",
            "/cache/import/good_two.mp4",
        ]
        assert len(scanner.failed) == 1

    def test_a_sidecar_with_no_media_is_reported_not_fatal(self, monkeypatch):
        monkeypatch.setattr(
            "appsettings.src.manual.AppConfig",
            lambda: type("C", (), {"config": {}})(),
        )
        monkeypatch.setattr(
            "appsettings.src.manual.countdown_sleep",
            lambda *args, **kwargs: True,
        )
        to_import = [
            {"media": False, "metadata": "/cache/import/orphan.info.json"},
            {"media": "/cache/import/good.mp4"},
        ]
        scanner = self.build_scanner(to_import, set())

        scanner.process_videos()

        assert scanner.imported == ["/cache/import/good.mp4"]
        assert len(scanner.failed) == 1
        assert "no matching media file found" in scanner.failed[0]

    @pytest.mark.parametrize(
        "err",
        [
            ValueError("no metadata"),
            # ffprobe on a truncated file
            subprocess.CalledProcessError(1, ["ffprobe", "-i", "bad.mp4"]),
            # the disk, or PIL on an unreadable thumbnail
            OSError("cannot identify image file"),
        ],
    )
    def test_survives_what_one_unusable_file_raises(self, monkeypatch, err):
        """a corrupt media file raises out of ffprobe, not as a
        ValueError"""
        monkeypatch.setattr(
            "appsettings.src.manual.AppConfig",
            lambda: type("C", (), {"config": {}})(),
        )
        monkeypatch.setattr(
            "appsettings.src.manual.countdown_sleep",
            lambda *args, **kwargs: True,
        )
        to_import = [
            {"media": "/cache/import/bad.mp4"},
            {"media": "/cache/import/good.mp4"},
        ]
        scanner = ImportFolderScanner()
        scanner.to_import = to_import
        scanner.imported = []

        def fake_process(current_video, config):
            # pylint: disable=unused-argument
            if current_video["media"] == "/cache/import/bad.mp4":
                raise err

            scanner.imported.append(current_video["media"])

        scanner._process_video = fake_process

        scanner.process_videos()

        assert scanner.imported == ["/cache/import/good.mp4"]
        # named, even though CalledProcessError stringifies to a command
        assert "bad.mp4" in scanner.failed[0]

    def test_scan_raises_once_with_every_reason(self, monkeypatch):
        """the run is still a failure, but the report covers all of it"""
        monkeypatch.setattr(
            "appsettings.src.manual.AppConfig",
            lambda: type("C", (), {"config": {}})(),
        )
        monkeypatch.setattr(
            "appsettings.src.manual.countdown_sleep",
            lambda *args, **kwargs: True,
        )
        to_import = [
            {"media": "/cache/import/bad_one.mp4"},
            {"media": "/cache/import/bad_two.mp4"},
        ]
        scanner = self.build_scanner(
            to_import,
            {"/cache/import/bad_one.mp4", "/cache/import/bad_two.mp4"},
        )
        monkeypatch.setattr(scanner, "get_all_files", list)
        monkeypatch.setattr(
            scanner,
            "match_files",
            lambda all_files: setattr(scanner, "to_import", to_import),
        )

        with pytest.raises(ValueError) as caught:
            scanner.scan()

        assert "bad_one.mp4" in str(caught.value)
        assert "bad_two.mp4" in str(caught.value)


class TestDetectYoutubeId:
    def test_names_the_file(self):
        """ "failed to find video id" alone is unactionable in a batch"""
        scanner = ImportFolderScanner()
        current_video = {
            "media": "/cache/import/mystery clip.mp4",
            "metadata": False,
        }

        with pytest.raises(ValueError) as caught:
            scanner._detect_youtube_id(current_video)

        assert "mystery clip.mp4" in str(caught.value)
