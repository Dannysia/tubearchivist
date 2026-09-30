"""test the generated info.json for manual import"""

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
    info_json = ImportFolderFiles.build_info_json(build_validated())

    for key in ["id", "title", "channel_id", "thumbnail", "uploader"]:
        assert key in info_json


def test_id_matches_the_video_id():
    assert ImportFolderFiles.build_info_json(build_validated())["id"] == (
        VIDEO_ID
    )


def test_upload_date_is_yt_dlp_spelled():
    info_json = ImportFolderFiles.build_info_json(build_validated())

    assert info_json["upload_date"] == "20091025"


def test_channel_name_maps_to_uploader():
    info_json = ImportFolderFiles.build_info_json(build_validated())

    assert info_json["uploader"] == "Rick Astley"


def test_optional_text_fields_fall_back_to_empty_rather_than_absent():
    validated = build_validated()
    for key in ["description", "thumbnail"]:
        validated.pop(key)

    info_json = ImportFolderFiles.build_info_json(validated)

    assert info_json["description"] == ""
    assert info_json["thumbnail"] == ""


def test_a_count_left_off_the_form_is_unknown_not_zero():
    validated = build_validated()
    for key in ["view_count", "like_count"]:
        validated.pop(key)

    info_json = ImportFolderFiles.build_info_json(validated)

    assert info_json["view_count"] == UNKNOWN_COUNT
    assert info_json["like_count"] == UNKNOWN_COUNT


@pytest.mark.parametrize("key", ["view_count", "like_count"])
def test_a_count_given_as_zero_is_a_real_zero(key):
    info_json = ImportFolderFiles.build_info_json(build_validated(**{key: 0}))

    assert info_json[key] == 0


def test_generated_name_passes_the_upload_name_gate():
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
    assert not is_safe_channel_id(channel_id)


@pytest.mark.parametrize(
    "channel_id",
    [CHANNEL_ID, "UC-lHJZR3Gqxm24_Vd_AJ5Yw", "my_custom_channel", "ab"],
)
def test_accepts_a_channel_id_usable_as_a_directory_name(channel_id):
    assert is_safe_channel_id(channel_id)


@pytest.mark.parametrize(
    "video_id",
    ["short", "waytoolongvideoid", "bad/id/here", "", None, "dQw4w9WgXc"],
)
def test_rejects_a_video_id_that_is_not_eleven_characters(video_id):
    assert not is_video_id(video_id)


def test_accepts_an_eleven_character_video_id():
    assert is_video_id(VIDEO_ID)


class TestMetadataName:
    @staticmethod
    @pytest.fixture
    def import_dir(tmp_path, monkeypatch):
        monkeypatch.setattr(ImportFolderFiles, "IMPORT_DIR", str(tmp_path))

        return tmp_path

    def test_follows_a_media_file_named_for_its_youtube_title(
        self, import_dir
    ):
        media = f"Some Title (with parens) [{VIDEO_ID}].mp4"
        (import_dir / media).touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"Some Title (with parens) [{VIDEO_ID}].info.json"
        )

    def test_matches_a_bare_id_media_file(self, import_dir):
        (import_dir / f"{VIDEO_ID}.mkv").touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_falls_back_to_the_bare_id_with_nothing_staged(self, import_dir):
        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_ignores_another_video_s_media_file(self, import_dir):
        (import_dir / "Other [hc5gku8LRTQ].mp4").touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_ignores_a_sidecar_that_is_not_media(self, import_dir):
        (import_dir / f"Some Title [{VIDEO_ID}].jpg").touch()
        (import_dir / f"Some Title [{VIDEO_ID}].en.vtt").touch()

        assert ImportFolderFiles.metadata_name(VIDEO_ID) == (
            f"{VIDEO_ID}.info.json"
        )

    def test_the_followed_name_still_passes_the_upload_name_gate(
        self, import_dir
    ):
        (import_dir / f"Some Title [{VIDEO_ID}].mp4").touch()
        clean_name = ImportFolderFiles.metadata_name(VIDEO_ID)

        assert ImportFolderFiles.validate_name(clean_name) == clean_name

    def test_the_followed_name_shares_the_media_file_s_base_name(
        self, import_dir
    ):
        media = f"Some Title [{VIDEO_ID}].mp4"
        (import_dir / media).touch()

        clean_name = ImportFolderFiles.metadata_name(VIDEO_ID)

        assert ImportFolderScanner._detect_base_name(clean_name)[0] == (
            ImportFolderScanner._detect_base_name(media)[0]
        )
