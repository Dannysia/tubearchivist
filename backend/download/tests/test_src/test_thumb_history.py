import io
import os

import pytest
from common.src.env_settings import EnvironmentSettings
from download.src import thumbnails
from download.src.thumbnails import ThumbManager, ThumbManagerBase
from PIL import Image, ImageDraw

VIDEO_ID = "abc123xyz00"


def _picture(color, quality=75, mark=None):
    img = Image.new("RGB", (1280, 720), color)
    if mark:
        ImageDraw.Draw(img).rectangle(mark, fill="white")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return Image.open(io.BytesIO(buffer.getvalue()))


@pytest.fixture(name="cache")
def fixture_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(EnvironmentSettings, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(ThumbManagerBase, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        ThumbManagerBase, "VIDEO_DIR", os.path.join(str(tmp_path), "videos")
    )
    return tmp_path


def _refresh(monkeypatch, img):
    manager = ThumbManager(VIDEO_ID)
    monkeypatch.setattr(manager, "fetch", lambda url: img)
    return manager.refresh_video_thumb("https://i.ytimg.com/vi/x/maxres.jpg")


def _cached(cache):
    with open(cache / "videos" / "a" / f"{VIDEO_ID}.jpg", "rb") as handle:
        return handle.read()


def _archived(cache):
    folder = cache / "history"
    if not folder.exists():
        return []

    return sorted(p.name for p in folder.rglob("*.jpg"))


def test_a_first_thumbnail_is_saved_without_history(cache, monkeypatch):
    old, new = _refresh(monkeypatch, _picture("red"))

    assert old == new
    assert thumbnails.image_hash(_cached(cache)) == new
    assert _archived(cache) == []


def test_an_unchanged_thumbnail_records_nothing(cache, monkeypatch):
    _refresh(monkeypatch, _picture("red"))

    old, new = _refresh(monkeypatch, _picture("red"))

    assert old == new
    assert _archived(cache) == []


def test_a_new_thumbnail_archives_the_old_one(cache, monkeypatch):
    _refresh(monkeypatch, _picture("red"))
    red = _cached(cache)

    old, new = _refresh(monkeypatch, _picture("blue"))

    assert old == thumbnails.image_hash(red)
    assert new == thumbnails.image_hash(_cached(cache))
    assert old != new
    path = thumbnails.archived_image_path(old, absolute=True)
    with open(path, "rb") as handle:
        assert handle.read() == red


def test_a_thumbnail_flipping_back_and_forth_is_stored_once_each(
    cache, monkeypatch
):
    _refresh(monkeypatch, _picture("red"))
    for _ in range(10):
        _refresh(monkeypatch, _picture("blue"))
        _refresh(monkeypatch, _picture("red"))

    assert len(_archived(cache)) == 2


def test_a_reencode_of_the_same_picture_is_not_a_change(cache, monkeypatch):
    _refresh(
        monkeypatch, _picture("red", quality=95, mark=(100, 100, 400, 300))
    )

    old, new = _refresh(
        monkeypatch, _picture("red", quality=60, mark=(100, 100, 400, 300))
    )

    assert old == new
    assert _archived(cache) == []


def test_a_small_edit_to_the_picture_is_a_change(cache, monkeypatch):
    _refresh(monkeypatch, _picture("red"))

    old, new = _refresh(monkeypatch, _picture("red", mark=(0, 0, 640, 360)))

    assert old != new
    assert len(_archived(cache)) == 1


def test_a_failed_download_keeps_the_current_thumbnail(cache, monkeypatch):
    _refresh(monkeypatch, _picture("red"))
    red = _cached(cache)

    old, new = _refresh(monkeypatch, None)

    assert old == new == thumbnails.image_hash(red)
    assert _cached(cache) == red
    assert _archived(cache) == []


def test_a_failed_first_download_still_writes_the_fallback(cache, monkeypatch):
    written = []
    monkeypatch.setattr(
        ThumbManager,
        "download_video_thumb",
        lambda self, url, skip_existing=False: written.append(url),
    )

    assert _refresh(monkeypatch, None) == (None, None)
    assert len(written) == 1


class _Response:
    def __init__(self, content, headers):
        self.content = content
        self.headers = headers


def _jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 9), "red").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_a_truncated_download_is_rejected():
    data = _jpeg()
    response = _Response(data[:-10], {"Content-Length": str(len(data))})

    assert thumbnails._open_image(response, "url") is None


def test_a_complete_download_opens():
    data = _jpeg()
    response = _Response(data, {"Content-Length": str(len(data))})

    assert thumbnails._open_image(response, "url").size == (16, 9)


def _write_cached(cache, data):
    folder = cache / "videos" / "a"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{VIDEO_ID}.jpg").write_bytes(data)


@pytest.mark.parametrize("broken", [b"", b"not a jpeg at all"])
def test_a_broken_cached_thumbnail_is_replaced_without_history(
    cache, monkeypatch, broken
):
    _write_cached(cache, broken)

    old, new = _refresh(monkeypatch, _picture("red"))

    assert old == new == thumbnails.image_hash(_cached(cache))
    assert _archived(cache) == []


def test_an_unchanged_thumbnail_is_not_rewritten(cache, monkeypatch):
    _refresh(monkeypatch, _picture("red"))
    written = []
    monkeypatch.setattr(
        thumbnails, "_write_atomic", lambda path, data: written.append(path)
    )

    _refresh(monkeypatch, _picture("red"))

    assert written == []


def test_overlapping_writes_to_one_thumbnail_both_land(tmp_path, monkeypatch):
    path = str(tmp_path / f"{VIDEO_ID}.jpg")
    real_replace = os.replace
    overlapped = []

    def replace_after_another_writer(src, dst):
        if not overlapped:
            overlapped.append(dst)
            thumbnails._write_atomic(path, b"second")
        real_replace(src, dst)

    monkeypatch.setattr(thumbnails.os, "replace", replace_after_another_writer)

    thumbnails._write_atomic(path, b"first")

    assert os.listdir(tmp_path) == [f"{VIDEO_ID}.jpg"]


def test_a_written_thumbnail_is_world_readable(tmp_path):
    path = tmp_path / f"{VIDEO_ID}.jpg"

    thumbnails._write_atomic(str(path), b"data")

    assert path.stat().st_mode & 0o777 == 0o644
