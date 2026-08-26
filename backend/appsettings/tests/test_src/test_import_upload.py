"""test import upload file name validation

validate_name is the only thing standing between an attacker controlled
upload name and a write to disk, so these pin the guarantees it makes
rather than just its happy path
"""

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
    """the bare video id with any extension the scanner imports"""
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
    """secondary extensions resolve to the same base name"""
    assert ImportFolderFiles.validate_name(file_name) == file_name


def test_accepts_yt_dlp_bracket_name():
    """the yt-dlp default output template"""
    file_name = f"Never Gonna Give You Up [{VIDEO_ID}].mp4"
    assert ImportFolderFiles.validate_name(file_name) == file_name


def test_accepts_uppercase_extension():
    """extension matching is case insensitive"""
    assert (
        ImportFolderFiles.validate_name(f"{VIDEO_ID}.MP4") == f"{VIDEO_ID}.MP4"
    )


def test_strips_surrounding_whitespace():
    """a padded name is still the same file"""
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
    """
    a traversing name never escapes the import folder, the directory
    part is dropped and only the file name survives
    """
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
    """
    a windows or encoded separator is not a path separator here, so the
    name keeps its dots and slashes and has to fail the id rule instead
    """
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize("file_name", ["", None, "   "])
def test_rejects_an_empty_name(file_name):
    """nothing to write"""
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize("file_name", [".bashrc", ".env", f".{VIDEO_ID}.mp4"])
def test_rejects_dotfiles(file_name):
    """a hidden file is never a staged import"""
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
    """only the extensions the import scanner knows, and never none"""
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
    """
    extract_video_id would take the trailing 11 characters of any name,
    so mystery-clip.mp4 would import as ystery-clip. the upload path
    insists on a name that cannot be misread
    """
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)


@pytest.mark.parametrize(
    "file_name",
    [
        # rejected on the extension
        f"{VIDEO_ID}.mp4\x00.txt",
        # keeps a valid extension, so the id rule has to catch it
        f"{VIDEO_ID}\x00.mp4",
        f"{VIDEO_ID}\x00.evil.mp4",
    ],
)
def test_rejects_a_null_byte_in_the_name(file_name):
    """a truncating name never reaches open()"""
    with pytest.raises(ValueError):
        ImportFolderFiles.validate_name(file_name)
