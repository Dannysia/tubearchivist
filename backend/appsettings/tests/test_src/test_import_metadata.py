"""test the generated info.json for manual import

build_info_json has to satisfy the import path, which reads some of
these keys with [] rather than .get() and raises without them - see
YoutubeVideo.process_youtube_meta and YoutubeChannel._video_fallback
"""

from datetime import date

import pytest
from appsettings.src.manual import (
    UNKNOWN_COUNT,
    ImportFolderFiles,
    ImportFolderScanner,
    is_safe_channel_id,
    is_video_id,
)

VIDEO_ID = "dQw4w9WgXcQ"
CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"


def build_validated(**overwrites):
    """validated serializer output"""
    validated = {
        "video_id": VIDEO_ID,
        "channel_id": CHANNEL_ID,
        "channel_name": "Rick Astley",
        "title": "Never Gonna Give You Up",
        "upload_date": date(2009, 10, 25),
        "description": "the official video",
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hq.jpg",
        "view_count": 1_600_000_000,
        "like_count": 18_000_000,
    }
    validated.update(overwrites)

    return validated


def test_carries_every_key_read_without_a_default():
    """these raise KeyError on the import path when missing"""
    info_json = ImportFolderFiles.build_info_json(build_validated())

    for key in ["id", "title", "channel_id", "thumbnail", "uploader"]:
        assert key in info_json


def test_id_matches_the_video_id():
    """_validate_id compares this against the file name's id"""
    assert ImportFolderFiles.build_info_json(build_validated())["id"] == (
        VIDEO_ID
    )


def test_upload_date_is_yt_dlp_spelled():
    """_build_published parses this with an exact %Y%m%d format"""
    info_json = ImportFolderFiles.build_info_json(build_validated())

    assert info_json["upload_date"] == "20091025"


def test_channel_name_maps_to_uploader():
    """_video_fallback reads fallback["uploader"] for the channel name"""
    info_json = ImportFolderFiles.build_info_json(build_validated())

    assert info_json["uploader"] == "Rick Astley"


def test_optional_text_fields_fall_back_to_empty_rather_than_absent():
    """the keys still have to exist, empty is fine"""
    validated = build_validated()
    for key in ["description", "thumbnail"]:
        validated.pop(key)

    info_json = ImportFolderFiles.build_info_json(validated)

    assert info_json["description"] == ""
    assert info_json["thumbnail"] == ""


def test_a_count_left_off_the_form_is_unknown_not_zero():
    """
    the video is gone and was never captured with its counts. 0 claims
    to know it had none, and reads as a real number wherever it is shown
    """
    validated = build_validated()
    for key in ["view_count", "like_count"]:
        validated.pop(key)

    info_json = ImportFolderFiles.build_info_json(validated)

    assert info_json["view_count"] == UNKNOWN_COUNT
    assert info_json["like_count"] == UNKNOWN_COUNT


@pytest.mark.parametrize("key", ["view_count", "like_count"])
def test_a_count_given_as_zero_is_a_real_zero(key):
    """
    the sentinel is for an absent count only - a hand entered 0 says
    the video really had none, and must survive as 0
    """
    info_json = ImportFolderFiles.build_info_json(build_validated(**{key: 0}))

    assert info_json[key] == 0


def test_generated_name_passes_the_upload_name_gate():
    """the scanner pairs <id>.info.json with <id>.mp4"""
    assert (
        ImportFolderFiles.validate_name(f"{VIDEO_ID}.info.json")
        == f"{VIDEO_ID}.info.json"
    )


@pytest.mark.parametrize(
    "channel_id",
    [
        "../../../etc",
        "..",
        "with/slash",
        "with.dot",
        "with space",
        "a",
        "",
        None,
    ],
)
def test_rejects_a_channel_id_that_is_not_a_safe_directory_name(channel_id):
    """
    channel_id becomes a directory under the media root through
    add_file_path and _move_to_archive, so it is charset restricted
    """
    assert not is_safe_channel_id(channel_id)


@pytest.mark.parametrize(
    "channel_id",
    [CHANNEL_ID, "UC-lHJZR3Gqxm24_Vd_AJ5Yw", "my_custom_channel", "ab"],
)
def test_accepts_a_channel_id_usable_as_a_directory_name(channel_id):
    """a real youtube id, and a hand made one for offline content"""
    assert is_safe_channel_id(channel_id)


@pytest.mark.parametrize(
    "video_id",
    ["short", "waytoolongvideoid", "bad/id/here", "", None, "dQw4w9WgXc"],
)
def test_rejects_a_video_id_that_is_not_eleven_characters(video_id):
    """the name has to be an unambiguous video id"""
    assert not is_video_id(video_id)


def test_accepts_an_eleven_character_video_id():
    """the happy path"""
    assert is_video_id(VIDEO_ID)


class TestMetadataName:
    """the generated info.json has to pair with its media file

    ImportFolderScanner.match_files joins a video's files by base name,
    so a media file staged under its full youtube name needs the sidecar
    under that same name - see the ValueError from process_videos
    """

    @staticmethod
    @pytest.fixture
    def import_dir(tmp_path, monkeypatch):
        """an empty import folder to stage files in"""
        monkeypatch.setattr(ImportFolderFiles, "IMPORT_DIR", str(tmp_path))

        return tmp_path

    def test_follows_a_media_file_named_for_its_youtube_title(
        self, import_dir
    ):
        """the spelling yt-dlp writes, and one validate_name accepts"""
        media = f"Some Title (with parens) [{VIDEO_ID}].mp4"
        (import_dir / media).touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"Some Title (with parens) [{VIDEO_ID}].info.json"
        )

    def test_matches_a_bare_id_media_file(self, import_dir):
        """the other spelling, where both names already agreed"""
        (import_dir / f"{VIDEO_ID}.mkv").touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_falls_back_to_the_bare_id_with_nothing_staged(self, import_dir):
        """metadata written before the media file arrives"""
        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_ignores_another_video_s_media_file(self, import_dir):
        """a busy import folder must not cross the two over"""
        (import_dir / "Other [hc5gku8LRTQ].mp4").touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_ignores_a_sidecar_that_is_not_media(self, import_dir):
        """only the media file decides the base name"""
        (import_dir / f"Some Title [{VIDEO_ID}].jpg").touch()
        (import_dir / f"Some Title [{VIDEO_ID}].en.vtt").touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_the_followed_name_still_passes_the_upload_name_gate(
        self, import_dir
    ):
        """write_metadata runs it through validate_name before writing"""
        (import_dir / f"Some Title [{VIDEO_ID}].mp4").touch()
        clean_name = ImportFolderFiles.metadata_name(VIDEO_ID)

        assert ImportFolderFiles.validate_name(clean_name) == clean_name

    def test_the_followed_name_shares_the_media_file_s_base_name(
        self, import_dir
    ):
        """which is the whole point: match_files groups on this"""
        media = f"Some Title [{VIDEO_ID}].mp4"
        (import_dir / media).touch()

        clean_name = ImportFolderFiles.metadata_name(VIDEO_ID)

        assert ImportFolderScanner._detect_base_name(clean_name)[0] == (
            ImportFolderScanner._detect_base_name(media)[0]
        )
