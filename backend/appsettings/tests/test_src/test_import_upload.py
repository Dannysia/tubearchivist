"""test import upload file name validation"""

import os

import pytest
from appsettings.src.manual import ImportFolderFiles

VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "file_name",
    [
        f"{VIDEO_ID}.mp4",
        f"{VIDEO_ID}.mkv",
        f"{VIDEO_ID}.webm",
        f"{VIDEO_ID}.json",
        f"{VIDEO_ID}.jpg",
        f"{VIDEO_ID}.png",
        f"{VIDEO_ID}.webp",
        f"{VIDEO_ID}.vtt",
    ],
)
def test_accepts_every_supported_extension(file_name):
    assert ImportFolderFiles.validate_name(file_name) == file_name


@pytest.mark.parametrize(
    "file_name",
    [
        f"{VIDEO_ID}.info.json",
        f"{VIDEO_ID}.en.vtt",
        f"{VIDEO_ID}.de.vtt",
    ],
)
def test_accepts_sidecar_names(file_name):
    assert ImportFolderFiles.validate_name(file_name) == file_name


def test_accepts_yt_dlp_bracket_name():
    file_name = f"Never Gonna Give You Up [{VIDEO_ID}].mp4"
    assert ImportFolderFiles.validate_name(file_name) == file_name


def test_accepts_uppercase_extension():
    assert (
        ImportFolderFiles.validate_name(f"{VIDEO_ID}.MP4") == f"{VIDEO_ID}.MP4"
    )


def test_strips_surrounding_whitespace():
    assert (
        ImportFolderFiles.validate_name(f"  {VIDEO_ID}.mp4  ")
        == f"{VIDEO_ID}.mp4"
    )


@pytest.mark.parametrize(
    "file_name",
    [
        f"../../{VIDEO_ID}.mp4",
        f"../../../etc/{VIDEO_ID}.mp4",
        f"/etc/cron.d/{VIDEO_ID}.mp4",
        f"subdir/{VIDEO_ID}.mp4",
    ],
)
def test_strips_any_path_from_the_name(file_name):
    clean_name = ImportFolderFiles.validate_name(file_name)

    assert clean_name == f"{VIDEO_ID}.mp4"
    assert "/" not in clean_name
    assert not clean_name.startswith("..")


@pytest.mark.parametrize(
    "file_name",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "../../../root/.ssh/authorized_keys",
        f"..\\..\\{VIDEO_ID}.mp4",
        f"..%2f..%2f{VIDEO_ID}.mp4",
    ],
)
def test_rejects_traversal_that_survives_basename(file_name):
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize("file_name", ["", None, "   "])
def test_rejects_an_empty_name(file_name):
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize("file_name", [".bashrc", ".env", f".{VIDEO_ID}.mp4"])
def test_rejects_dotfiles(file_name):
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize(
    "file_name",
    [
        f"{VIDEO_ID}.exe",
        f"{VIDEO_ID}.sh",
        f"{VIDEO_ID}.py",
        f"{VIDEO_ID}.mp4.exe",
        VIDEO_ID,
    ],
)
def test_rejects_unsupported_extensions(file_name):
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize(
    "file_name",
    [
        "mystery-clip.mp4",
        "My Holiday Video.mp4",
        f"prefix {VIDEO_ID}.mp4",
        f"{VIDEO_ID}extra.mp4",
        "short.mp4",
        f"[{VIDEO_ID}]trailing.mp4",
    ],
)
def test_rejects_names_that_are_not_an_unambiguous_video_id(file_name):
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize(
    "file_name",
    [
        f"{VIDEO_ID}.mp4\x00.txt",
        f"{VIDEO_ID}\x00.mp4",
        f"{VIDEO_ID}\x00.evil.mp4",
    ],
)
def test_rejects_a_null_byte_in_the_name(file_name):
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


class TestStagedFilePath:
    @staticmethod
    @pytest.fixture
    def import_dir(tmp_path, monkeypatch):
        monkeypatch.setattr(ImportFolderFiles, "IMPORT_DIR", str(tmp_path))
        (tmp_path / "staged.mp4").write_bytes(b"data")

        return tmp_path

    def test_resolves_a_staged_file(self, import_dir):
        assert ImportFolderFiles.file_path("staged.mp4") == str(
            import_dir / "staged.mp4"
        )

    def test_a_name_with_no_such_file_is_none_not_an_error(self, import_dir):
        assert ImportFolderFiles.file_path("nothing.mp4") is None

    @pytest.mark.parametrize("file_name", ["", "   ", None, ".hidden"])
    def test_refuses_an_unusable_name(self, import_dir, file_name):
        with pytest.raises(ValueError):
            ImportFolderFiles.file_path(file_name)

    @pytest.mark.parametrize(
        "file_name", ["../../../etc/passwd", "/etc/passwd", "../secret.mp4"]
    )
    def test_a_traversal_naming_nothing_staged_resolves_to_nothing(
        self, import_dir, file_name
    ):
        assert ImportFolderFiles.file_path(file_name) is None

    @pytest.mark.parametrize(
        "file_name", ["subdir/staged.mp4", "../staged.mp4", "/etc/staged.mp4"]
    )
    def test_a_path_can_never_resolve_outside_the_import_folder(
        self, import_dir, file_name
    ):
        resolved = ImportFolderFiles.file_path(file_name)

        assert resolved == str(import_dir / "staged.mp4")
        assert os.path.dirname(resolved) == str(import_dir)

    def test_a_traversal_onto_a_real_outside_file_is_not_reachable(
        self, import_dir, tmp_path
    ):
        (tmp_path.parent / "outside.mp4").write_bytes(b"secret")

        assert ImportFolderFiles.file_path("../outside.mp4") is None

    def test_delete_still_refuses_the_same_names(self, import_dir):
        with pytest.raises(ValueError):
            ImportFolderFiles.delete_file(".hidden")

        assert ImportFolderFiles.delete_file("nothing.mp4") is False
        assert ImportFolderFiles.delete_file("staged.mp4") is True
