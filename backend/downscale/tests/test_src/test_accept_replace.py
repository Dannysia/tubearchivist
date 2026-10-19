import os
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import IndexWriteError
from downscale.src.downscale import (
    DownscaleReview,
    _boxes_fill_file,
    verify_encode,
)
from downscale.src.queue_interact import DownscaleInteract
from redis.exceptions import LockNotOwnedError

DOC_ID = "video1"
needs_ffmpeg = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not on PATH"
)


def _make_clip(path, duration=6, faststart=True):
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=duration={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
    ]
    if faststart:
        cmd += ["-movflags", "+faststart"]

    subprocess.run([*cmd, str(path)], check=True)
    return path


@pytest.fixture(name="clip", scope="module")
def fixture_clip(tmp_path_factory):
    return _make_clip(tmp_path_factory.mktemp("clips") / "clip.mp4")


@needs_ffmpeg
def test_a_healthy_encode_passes(clip):
    assert verify_encode(str(clip), str(clip), clip.stat().st_size) is None


@needs_ffmpeg
def test_an_encode_without_faststart_passes(tmp_path, clip):
    plain = _make_clip(tmp_path / "plain.mp4", faststart=False)

    assert verify_encode(str(plain), str(clip), plain.stat().st_size) is None


@needs_ffmpeg
@pytest.mark.parametrize("cut", [1, 1000, 0.5])
def test_a_truncated_encode_fails(tmp_path, clip, cut):
    data = clip.read_bytes()
    keep = int(len(data) * cut) if cut < 1 else len(data) - cut
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(data[:keep])

    error = verify_encode(str(truncated), str(clip), keep)

    assert error == "the encode is truncated, original kept"


@needs_ffmpeg
def test_an_encode_that_changed_size_fails(clip):
    error = verify_encode(str(clip), str(clip), clip.stat().st_size + 1)

    assert "original kept" in error


def _reencode(src, dst, *args):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), *args]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy"]
    subprocess.run([*cmd, "-movflags", "+faststart", str(dst)], check=True)
    return dst


@needs_ffmpeg
def test_a_real_downscale_matches_frame_for_frame(tmp_path, clip):
    encode = _reencode(clip, tmp_path / "encode.mp4", "-vf", "scale=-2:120")

    assert verify_encode(str(encode), str(clip), encode.stat().st_size) is None


@needs_ffmpeg
def test_a_frame_rate_change_fails(tmp_path, clip):
    encode = _reencode(clip, tmp_path / "encode.mp4", "-r", "25")

    error = verify_encode(str(encode), str(clip), encode.stat().st_size)

    assert "frames but the original has 180" in error


@needs_ffmpeg
def test_a_short_encode_fails(tmp_path, clip):
    short = _make_clip(tmp_path / "short.mp4", duration=2)

    error = verify_encode(str(short), str(clip), short.stat().st_size)

    assert error == "the encode has 60 frames but the original has 180, " + (
        "original kept"
    )


@pytest.mark.parametrize(
    "encode_timing, expected",
    [
        (("3600.000000", "86400"), None),
        (("3600.000000", "86399"), "86399 frames"),
        (("3600.001000", "86400"), "3600.001000s long"),
        (None, "could not read the frame count"),
    ],
)
def test_frames_and_duration_must_match_exactly(encode_timing, expected):
    timings = {"original": ("3600.000000", "86400"), "encode": encode_timing}
    with patch(
        "downscale.src.downscale._get_timing",
        side_effect=lambda path: timings[path],
    ), patch(
        "downscale.src.downscale._boxes_fill_file", return_value=True
    ), patch(
        "downscale.src.downscale.os.path.getsize", return_value=1
    ):
        error = verify_encode("encode", "original", 1)

    if expected is None:
        assert error is None
    else:
        assert expected in error and error.endswith("original kept")


def test_trailing_bytes_after_the_last_box_fail(tmp_path):
    path = tmp_path / "trailing.mp4"
    path.write_bytes((8).to_bytes(4, "big") + b"ftyp" + b"\x00\x00\x00")

    assert not _boxes_fill_file(str(path))


def test_a_truncated_largesize_box_fails(tmp_path):
    path = tmp_path / "large.mp4"
    header = (1).to_bytes(4, "big") + b"mdat" + (10**9).to_bytes(8, "big")
    path.write_bytes(header + b"\x00" * 100)

    assert not _boxes_fill_file(str(path))


def _files(tmp_path):
    channel = tmp_path / "media" / "channel"
    channel.mkdir(parents=True)
    original = channel / "video1.mp4"
    original.write_bytes(b"original")
    original.chmod(0o644)
    encode = tmp_path / "cache" / "video1_480p.mp4"
    encode.parent.mkdir()
    encode.write_bytes(b"encode")
    encode.chmod(0o600)
    return channel, original, encode


def _leftovers(channel):
    return sorted(p.name for p in channel.iterdir() if p.name.startswith("."))


def test_replace_swaps_the_file_and_keeps_a_hardlink_backup(tmp_path):
    channel, original, encode = _files(tmp_path)
    original_inode = original.stat().st_ino

    backup = DownscaleReview(DOC_ID)._replace(str(encode), str(original))

    assert original.read_bytes() == b"encode"
    assert encode.read_bytes() == b"encode"
    assert os.stat(backup).st_ino == original_inode
    assert _leftovers(channel) == [".video1.downscale-backup"]


def test_replace_keeps_the_originals_mode(tmp_path):
    _, original, encode = _files(tmp_path)

    DownscaleReview(DOC_ID)._replace(str(encode), str(original))

    assert original.stat().st_mode & 0o777 == 0o644


def test_replace_copies_the_backup_without_hardlinks(tmp_path):
    channel, original, encode = _files(tmp_path)

    with patch("downscale.src.downscale.os.link", side_effect=OSError(1)):
        backup = DownscaleReview(DOC_ID)._replace(str(encode), str(original))

    assert original.read_bytes() == b"encode"
    with open(backup, "rb") as backup_file:
        assert backup_file.read() == b"original"
    assert _leftovers(channel) == [".video1.downscale-backup"]


@pytest.mark.parametrize(
    "err", [OSError(28, "No space left on device"), LockNotOwnedError("gone")]
)
def test_a_failed_copy_leaves_nothing_behind(tmp_path, err):
    channel, original, encode = _files(tmp_path)
    review = DownscaleReview(DOC_ID)

    def keep_alive():
        raise err

    review._keep_alive = keep_alive
    with pytest.raises(type(err)):
        review._replace(str(encode), str(original))

    assert original.read_bytes() == b"original"
    assert encode.read_bytes() == b"encode"
    assert _leftovers(channel) == []


def test_accept_keeps_its_lock_alive_while_copying(tmp_path):
    _, original, encode = _files(tmp_path)
    lock = MagicMock()

    with patch("downscale.src.downscale.RedisBase") as redis_base, patch(
        "downscale.src.downscale.COPY_CHUNK_SIZE", 2
    ), patch.object(DownscaleReview, "_accept") as accept:
        redis_base.return_value.conn.lock.return_value = lock
        review = DownscaleReview(DOC_ID)
        accept.side_effect = lambda: review._replace(
            str(encode), str(original)
        )
        review.accept()

    assert lock.extend.call_count == 3
    lock.release.assert_called_once()


def test_a_crash_before_the_swap_does_not_block_the_next_accept(tmp_path):
    channel, original, encode = _files(tmp_path)
    os.link(original, channel / ".video1.downscale-backup")
    (channel / ".video1.downscale-staging").write_bytes(b"enc")

    backup = DownscaleReview(DOC_ID)._replace(str(encode), str(original))

    assert original.read_bytes() == b"encode"
    with open(backup, "rb") as backup_file:
        assert backup_file.read() == b"original"
    assert _leftovers(channel) == [".video1.downscale-backup"]


def test_a_crash_after_the_swap_is_rolled_back_first(tmp_path):
    channel, original, encode = _files(tmp_path)
    (channel / ".video1.downscale-backup").write_bytes(b"true original")

    backup = DownscaleReview(DOC_ID)._replace(str(encode), str(original))

    assert original.read_bytes() == b"encode"
    with open(backup, "rb") as backup_file:
        assert backup_file.read() == b"true original"


def _accept(tmp_path, upload_error=None):
    channel, original, encode = _files(tmp_path)
    job = {
        "youtube_id": DOC_ID,
        "target_height": 480,
        "current_height": 1080,
        "original_size": 8,
        "new_size": 6,
        "status": "pending_review",
        "tmp_file_path": str(encode),
    }
    video = MagicMock()
    video.json_data = {"media_url": "channel/video1.mp4"}

    def add_streams(media_path=False):
        video.json_data["streams"] = [{"type": "video", "index": 0}]

    video.add_streams.side_effect = add_streams
    video.upload_to_es.side_effect = upload_error

    with patch.object(
        EnvironmentSettings, "MEDIA_DIR", str(tmp_path / "media")
    ), patch("downscale.src.downscale.RedisBase"), patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch.object(
        DownscaleInteract, "delete_item"
    ) as delete, patch.object(
        DownscaleInteract, "update"
    ) as update, patch(
        "downscale.src.downscale.YoutubeVideo", return_value=video
    ), patch(
        "downscale.src.downscale.verify_encode", return_value=None
    ):
        error = DownscaleReview(DOC_ID).accept()

    return error, channel, original, encode, delete, update


def test_accept_end_to_end(tmp_path):
    error, channel, original, encode, delete, _ = _accept(tmp_path)

    assert error is None
    assert original.read_bytes() == b"encode"
    assert not encode.exists()
    assert _leftovers(channel) == []
    delete.assert_called_once()


def test_accept_end_to_end_with_a_failed_index_write(tmp_path):
    error, channel, original, encode, delete, update = _accept(
        tmp_path, upload_error=IndexWriteError("es answered 503")
    )

    assert error == "the index was not updated, original kept: es answered 503"
    assert original.read_bytes() == b"original"
    assert encode.read_bytes() == b"encode"
    assert _leftovers(channel) == []
    delete.assert_not_called()
    update.assert_not_called()
