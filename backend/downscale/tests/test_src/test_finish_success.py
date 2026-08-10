"""
tests for _finish_success() persisting the exact ffmpeg argv that
produced the candidate file - the only unambiguous provenance record
once encodes can come from heterogeneous encoders/hosts (see
docs/remote-downscale)
"""

from unittest.mock import patch

from downscale.src.downscale import DownscaleRunner
from downscale.src.queue_interact import DownscaleInteract


def _make_runner():
    runner = DownscaleRunner(
        task=None, youtube_id="video1", target_height=480, doc_id="doc1"
    )
    runner.tmp_path = "/cache/downscale/video1_480p.mp4"
    runner.encoder_key = "h264"
    runner.quality = 23
    runner.preset = "veryfast"
    runner.cmd = ["ffmpeg", "-y", "-i", "/original.mp4", "-c:v", "libx264"]
    return runner


def test_finish_success_persists_shlex_joined_argv():
    """the exact argv used for this encode is stored as ffmpeg_args"""
    runner = _make_runner()

    with patch("downscale.src.downscale._get_height", return_value=480), patch(
        "downscale.src.downscale.MediaStreamExtractor"
    ) as mock_extractor, patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.downscale.dispatch_pending_downscales"
    ):
        mock_extractor.return_value.get_file_size.return_value = 1234

        runner._finish_success()

    kwargs = mock_update.call_args.kwargs
    assert kwargs["ffmpeg_args"] == "ffmpeg -y -i /original.mp4 -c:v libx264"


def test_finish_success_with_no_cmd_stores_empty_string():
    """defensive fallback if _finish_success is ever reached without cmd set"""
    runner = _make_runner()
    runner.cmd = None

    with patch("downscale.src.downscale._get_height", return_value=480), patch(
        "downscale.src.downscale.MediaStreamExtractor"
    ) as mock_extractor, patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.downscale.dispatch_pending_downscales"
    ):
        mock_extractor.return_value.get_file_size.return_value = 1234

        runner._finish_success()

    kwargs = mock_update.call_args.kwargs
    assert kwargs["ffmpeg_args"] == ""
