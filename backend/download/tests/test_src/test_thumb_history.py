import io
import os

import pytest
from common.src.env_settings import EnvironmentSettings
from download.src import thumbnails
from download.src.thumbnails import ThumbManager, ThumbManagerBase
from PIL import Image

VIDEO_ID = "abc123xyz00"


def _source(color, image_format="JPEG", size=(1280, 720)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture(name="cache")
def fixture_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(EnvironmentSettings, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(ThumbManagerBase, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        ThumbManagerBase, "VIDEO_DIR", os.path.join(str(tmp_path), "videos")
    )
    return tmp_path


def _manager(monkeypatch, source):
    manager = ThumbManager(VIDEO_ID)
    monkeypatch.setattr(manager, "fetch_bytes", lambda url: source)
    return manager


def _refresh(monkeypatch, source):
    manager = _manager(monkeypatch, source)
    return manager.refresh_video_thumb("https://i.ytimg.com/vi/x/maxres.jpg")


def _download(monkeypatch, source):
    manager = _manager(monkeypatch, source)
    manager.download_video_thumb("https://i.ytimg.com/vi/x/maxres.jpg")


def _cached_path(cache):
    return cache / "videos" / "a" / f"{VIDEO_ID}.jpg"


def _cached(cache):
    return _cached_path(cache).read_bytes()


def _write_cached(cache, data):
    _cached_path(cache).parent.mkdir(parents=True, exist_ok=True)
    _cached_path(cache).write_bytes(data)


def _archived(cache):
    folder = cache / "history"
    if not folder.exists():
        return []

    return sorted(p.name for p in folder.rglob("*.jpg"))


def _original(digest):
    with open(
        thumbnails.archived_image_path(digest, absolute=True), "rb"
    ) as f:
        return f.read()


def test_a_downloaded_thumbnail_keeps_the_original(cache, monkeypatch):
    red = _source("red")

    _download(monkeypatch, red)

    digest = thumbnails.image_hash(red)
    assert _original(digest) == red
    assert thumbnails._video_thumb_source(_cached(cache)) == digest


def test_a_failed_download_writes_the_fallback_without_an_original(
    cache, monkeypatch
):
    _download(monkeypatch, None)

    assert Image.open(_cached_path(cache)).size[0] > 0
    assert thumbnails._video_thumb_source(_cached(cache)) is None
    assert _archived(cache) == []


def test_the_cached_thumbnail_is_a_cropped_jpeg_of_a_webp_original(
    cache, monkeypatch
):
    webp = _source("red", image_format="WEBP", size=(480, 360))

    _download(monkeypatch, webp)

    cached = Image.open(_cached_path(cache))
    assert cached.format == "JPEG"
    assert cached.size == (480, 270)
    assert _original(thumbnails.image_hash(webp)) == webp


def test_a_first_refresh_saves_the_thumbnail_without_history(
    cache, monkeypatch
):
    red = _source("red")

    old, new = _refresh(monkeypatch, red)

    assert old == new == thumbnails.image_hash(red)
    assert _original(new) == red


def test_an_unchanged_original_records_nothing(cache, monkeypatch):
    _download(monkeypatch, _source("red"))

    old, new = _refresh(monkeypatch, _source("red"))

    assert old == new
    assert _archived(cache) == [f"{new}.jpg"]


def test_an_unchanged_original_is_not_rewritten(cache, monkeypatch):
    _download(monkeypatch, _source("red"))
    written = []
    monkeypatch.setattr(
        thumbnails, "_write_atomic", lambda path, data: written.append(path)
    )

    _refresh(monkeypatch, _source("red"))

    assert written == []


def test_a_new_original_is_a_change_and_both_are_kept(cache, monkeypatch):
    red, blue = _source("red"), _source("blue")
    _download(monkeypatch, red)

    old, new = _refresh(monkeypatch, blue)

    assert old == thumbnails.image_hash(red)
    assert new == thumbnails.image_hash(blue)
    assert _original(old) == red
    assert _original(new) == blue
    assert thumbnails._video_thumb_source(_cached(cache)) == new


def test_a_thumbnail_flipping_back_and_forth_is_stored_once_each(
    cache, monkeypatch
):
    _download(monkeypatch, _source("red"))
    for _ in range(10):
        _refresh(monkeypatch, _source("blue"))
        _refresh(monkeypatch, _source("red"))

    assert len(_archived(cache)) == 2


def test_a_missing_original_is_stored_again(cache, monkeypatch):
    red = _source("red")
    _download(monkeypatch, red)
    os.remove(thumbnails.archived_image_path(thumbnails.image_hash(red), True))

    _refresh(monkeypatch, red)

    assert _original(thumbnails.image_hash(red)) == red


@pytest.mark.parametrize(
    "cached",
    [b"", b"not a jpeg at all", _source("blue")],
    ids=["empty", "corrupt", "without original"],
)
def test_an_unknown_cached_thumbnail_starts_history_fresh(
    cache, monkeypatch, cached
):
    _write_cached(cache, cached)
    red = _source("red")

    old, new = _refresh(monkeypatch, red)

    assert old == new == thumbnails.image_hash(red)
    assert thumbnails._video_thumb_source(_cached(cache)) == new


def test_a_failed_refresh_keeps_the_current_thumbnail(cache, monkeypatch):
    _download(monkeypatch, _source("red"))
    current = _cached(cache)

    old, new = _refresh(monkeypatch, None)

    assert old == new == thumbnails.image_hash(_source("red"))
    assert _cached(cache) == current


def test_a_failed_first_refresh_still_writes_the_fallback(cache, monkeypatch):
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


def test_a_truncated_download_is_rejected():
    data = _source("red", size=(16, 9))
    response = _Response(data[:-10], {"Content-Length": str(len(data))})

    assert thumbnails._response_bytes(response, "url") is None


def test_a_download_that_is_not_an_image_is_rejected():
    response = _Response(b"<html>", {})

    assert thumbnails._response_bytes(response, "url") is None


def test_a_complete_download_is_returned_as_is():
    data = _source("red", size=(16, 9))
    response = _Response(data, {"Content-Length": str(len(data))})

    assert thumbnails._response_bytes(response, "url") == data


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
