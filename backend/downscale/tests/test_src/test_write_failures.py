"""a failed queue write has to leave the job somewhere recoverable"""

from types import SimpleNamespace
from unittest.mock import patch

from common.src.es_connect import IndexWriteError
from common.src.queue_interact import QueueDocMissing
from downscale.src.downscale import DownscaleRunner
from downscale.src.queue_interact import DownscaleInteract
from downscale.tests.helpers import make_runner


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
    runner = make_runner(SimpleNamespace(is_stopped=lambda: False))

    with patch(
        "downscale.src.downscale.YoutubeVideo", return_value=_video()
    ), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale._get_height", return_value=1080
    ), patch.object(
        DownscaleRunner, "_reserve_slot", return_value=True
    ), patch.object(
        DownscaleRunner, "_encode", side_effect=IndexWriteError("es down")
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
    runner = make_runner(SimpleNamespace(is_stopped=lambda: False))

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
    runner = make_runner(SimpleNamespace(is_stopped=lambda: False))

    with patch.object(DownscaleRunner, "_cleanup_tmp"), patch.object(
        DownscaleInteract, "update", side_effect=IndexWriteError("es down")
    ), patch(
        "downscale.src.downscale.dispatch_pending_downscales"
    ) as mock_dispatch:
        runner._mark_crashed(RuntimeError("ffmpeg died"))

    mock_dispatch.assert_called_once()


class Retry(Exception):
    pass


def _retrying_runner():
    retries = []

    def retry(countdown=None):
        retries.append(countdown)
        return Retry()

    runner = make_runner(
        SimpleNamespace(is_stopped=lambda: False, retry=retry)
    )
    return runner, retries


def test_a_failed_pre_flight_write_retries_the_job():
    runner, retries = _retrying_runner()

    with patch(
        "downscale.src.downscale.YoutubeVideo", return_value=_video()
    ), patch(
        "downscale.src.downscale.os.path.exists", return_value=False
    ), patch.object(
        DownscaleInteract, "update", side_effect=IndexWriteError("es down")
    ), patch.object(
        DownscaleRunner, "_encode"
    ) as mock_encode:
        try:
            runner.run()
        except Retry:
            pass

    assert len(retries) == 1
    mock_encode.assert_not_called()


def test_a_failed_slot_reservation_write_retries_the_job():
    runner, retries = _retrying_runner()

    with patch(
        "downscale.src.downscale.YoutubeVideo", return_value=_video()
    ), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale._get_height", return_value=1080
    ), patch.object(
        DownscaleRunner,
        "_reserve_slot",
        side_effect=IndexWriteError("es down"),
    ), patch.object(
        DownscaleRunner, "_encode"
    ) as mock_encode:
        try:
            runner.run()
        except Retry:
            pass

    assert len(retries) == 1
    mock_encode.assert_not_called()


def test_a_job_deleted_under_the_runner_is_not_retried():
    runner, retries = _retrying_runner()

    with patch(
        "downscale.src.downscale.YoutubeVideo", return_value=_video()
    ), patch(
        "downscale.src.downscale.os.path.exists", return_value=False
    ), patch.object(
        DownscaleInteract, "update", side_effect=QueueDocMissing("gone")
    ), patch.object(
        DownscaleRunner, "_encode"
    ) as mock_encode:
        runner.run()

    assert retries == []
    mock_encode.assert_not_called()
