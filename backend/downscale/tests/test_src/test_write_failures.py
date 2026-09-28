"""a failed queue write has to leave the job somewhere recoverable"""

from types import SimpleNamespace
from unittest.mock import patch

from common.src.queue_interact import QueueWriteError
from downscale.src.downscale import DownscaleRunner
from downscale.src.queue_interact import DownscaleInteract


def _runner():
    return DownscaleRunner(
        task=SimpleNamespace(is_stopped=lambda: False),
        youtube_id="video1",
        target_height=480,
        doc_id="doc1",
    )


def _video():
    return SimpleNamespace(
        json_data={
            "media_url": "channel/video1.mp4",
            "title": "a title",
            "player": {"duration": 10},
        },
        get_from_es=lambda: None,
    )


def test_a_failed_status_write_frees_the_slot_and_says_why():
    runner = _runner()

    with patch(
        "downscale.src.downscale.YoutubeVideo", return_value=_video()
    ), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale._get_height", return_value=1080
    ), patch.object(
        DownscaleRunner, "_reserve_slot", return_value=True
    ), patch.object(
        DownscaleRunner, "_encode", side_effect=QueueWriteError("es down")
    ), patch.object(
        DownscaleRunner, "_cleanup_tmp"
    ) as mock_cleanup, patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.downscale.dispatch_pending_downscales"
    ) as mock_dispatch:
        runner.run()

    mock_cleanup.assert_called_once()
    assert mock_update.call_args.kwargs["status"] == "failed"
    assert "es down" in mock_update.call_args.kwargs["message"]
    mock_dispatch.assert_called_once()


def test_a_real_encode_failure_still_cleans_up_and_marks_it_failed():
    runner = _runner()

    with patch(
        "downscale.src.downscale.YoutubeVideo", return_value=_video()
    ), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale._get_height", return_value=1080
    ), patch.object(
        DownscaleRunner, "_reserve_slot", return_value=True
    ), patch.object(
        DownscaleRunner, "_encode", side_effect=RuntimeError("ffmpeg died")
    ), patch.object(
        DownscaleRunner, "_cleanup_tmp"
    ) as mock_cleanup, patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.downscale.dispatch_pending_downscales"
    ):
        runner.run()

    mock_cleanup.assert_called_once()
    assert mock_update.call_args.kwargs["status"] == "failed"
    assert "ffmpeg died" in mock_update.call_args.kwargs["message"]


def test_mark_crashed_keeps_the_real_error_when_its_own_write_fails():
    runner = _runner()

    with patch.object(DownscaleRunner, "_cleanup_tmp"), patch.object(
        DownscaleInteract, "update", side_effect=QueueWriteError("es down")
    ), patch(
        "downscale.src.downscale.dispatch_pending_downscales"
    ) as mock_dispatch:
        runner._mark_crashed(RuntimeError("ffmpeg died"))

    mock_dispatch.assert_called_once()
