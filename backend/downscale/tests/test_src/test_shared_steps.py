"""test the shared downscale steps"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from downscale.src import downscale
from downscale.src.queue_interact import (
    ALREADY_ACTIVE,
    FAILED_MESSAGE_LIMIT,
    TARGET_NOT_BELOW,
    DownscaleInteract,
    max_video_height,
)


def _video(height):
    streams = [{"type": "audio"}]
    if height:
        streams.append({"type": "video", "height": height})

    return {
        "youtube_id": "vid1",
        "title": "a title",
        "channel": {"channel_id": "UC1", "channel_name": "a channel"},
        "media_url": "UC1/vid1.mp4",
        "streams": streams,
    }


def test_max_video_height_ignores_audio_and_handles_none():
    streams = [
        {"type": "audio"},
        {"type": "video", "height": 720},
        {"type": "video", "height": 1080},
    ]
    assert max_video_height(streams) == 1080
    assert max_video_height([{"type": "audio"}]) is None


@pytest.mark.parametrize("height", [480, 360, None])
def test_enqueue_refuses_a_target_not_below_the_video(height):
    with patch.object(DownscaleInteract, "create") as mock_create:
        assert DownscaleInteract.enqueue(_video(height), 480) == (
            None,
            TARGET_NOT_BELOW,
        )

    mock_create.assert_not_called()


def test_enqueue_refuses_a_video_with_an_active_job():
    with patch.object(
        DownscaleInteract, "get_active_for_video", return_value={"id": "x"}
    ), patch.object(DownscaleInteract, "create") as mock_create:
        assert DownscaleInteract.enqueue(_video(1080), 480) == (
            None,
            ALREADY_ACTIVE,
        )

    mock_create.assert_not_called()


def test_enqueue_creates_a_queued_job():
    with patch.object(
        DownscaleInteract, "get_active_for_video", return_value=None
    ), patch.object(
        DownscaleInteract, "create", return_value="vid1"
    ) as mock_create:
        assert DownscaleInteract.enqueue(_video(1080), 480) == ("vid1", None)

    doc = mock_create.call_args.args[0]
    assert doc["status"] == "queued"
    assert (doc["current_height"], doc["target_height"]) == (1080, 480)


def test_mark_failed_trims_the_message_and_stamps_it():
    with patch.object(DownscaleInteract, "update") as mock_update:
        DownscaleInteract("doc1").mark_failed("x" * 5000, worker="")

    kwargs = mock_update.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert len(kwargs["message"]) == FAILED_MESSAGE_LIMIT
    assert kwargs["updated"] > 0
    assert kwargs["worker"] == ""


@pytest.mark.parametrize("acquired", [True, False])
def test_dispatch_lock_releases_only_what_it_took(acquired):
    lock = MagicMock()
    lock.acquire.return_value = acquired

    with patch.object(downscale, "RedisBase") as redis:
        redis.return_value.conn.lock.return_value = lock
        with downscale.dispatch_lock() as got:
            assert got is acquired

    assert lock.release.called is acquired


def test_dispatch_lock_releases_when_the_body_raises():
    lock = MagicMock()
    lock.acquire.return_value = True

    with patch.object(downscale, "RedisBase") as redis:
        redis.return_value.conn.lock.return_value = lock
        with pytest.raises(RuntimeError):
            with downscale.dispatch_lock():
                raise RuntimeError("boom")

    lock.release.assert_called_once()


def _source(monkeypatch, json_data, exists=True, height=1080):
    video = SimpleNamespace(json_data=json_data, get_from_es=lambda: None)
    monkeypatch.setattr(downscale, "YoutubeVideo", lambda youtube_id: video)
    monkeypatch.setattr(downscale.os.path, "exists", lambda path: exists)
    monkeypatch.setattr(downscale, "_get_height", lambda path: height)
    calls = []
    monkeypatch.setattr(
        DownscaleInteract, "delete_item", lambda self: calls.append("delete")
    )
    monkeypatch.setattr(
        DownscaleInteract,
        "mark_failed",
        lambda self, message: calls.append(message),
    )
    return calls


def test_check_source_drops_a_job_whose_video_is_gone(monkeypatch):
    calls = _source(monkeypatch, None)

    assert downscale.check_source("doc1", "vid1", 480) is None
    assert calls == ["delete"]


def test_check_source_fails_a_job_whose_file_is_missing(monkeypatch):
    calls = _source(monkeypatch, _video(1080), exists=False)

    assert downscale.check_source("doc1", "vid1", 480) is None
    assert calls == ["source file missing"]


def test_check_source_fails_a_job_no_longer_needed(monkeypatch):
    calls = _source(monkeypatch, _video(1080), height=480)

    assert downscale.check_source("doc1", "vid1", 480) is None
    assert calls == ["target height no longer below current height"]


def test_check_source_hands_back_what_the_encode_needs(monkeypatch):
    calls = _source(monkeypatch, _video(1080))

    source = downscale.check_source("doc1", "vid1", 480)

    assert calls == []
    assert source["current_height"] == 1080
    assert source["original_path"].endswith("UC1/vid1.mp4")
