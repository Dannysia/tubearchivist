"""tests for accepting a finished downscale job"""

from unittest.mock import MagicMock, patch

from downscale.src.downscale import DownscaleReview
from downscale.src.queue_interact import DownscaleInteract

DOC_ID = "abc123"

PENDING_JOB = {
    "youtube_id": "video1",
    "target_height": 480,
    "current_height": 1080,
    "original_size": 5000,
    "new_size": 1000,
    "status": "pending_review",
    "tmp_file_path": "/cache/downscale/video1_480p.mp4",
    "encoder": "h264",
    "quality": 23,
    "preset": "veryfast",
    "ffmpeg_args": "ffmpeg -y -i /original.mp4 -c:v libx264",
}


def _mock_video(json_data):
    video = MagicMock()
    video.json_data = json_data
    return video


def test_accept_copies_ffmpeg_args_onto_the_video():
    """
    the exact argv that produced the accepted file becomes part of the
    video's permanent downscale record, alongside encoder/quality/preset
    """
    video = _mock_video({"media_url": "video1.mp4"})

    with patch.object(
        DownscaleInteract, "get_item", return_value=(PENDING_JOB, 200)
    ), patch.object(DownscaleInteract, "delete_item"), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale.YoutubeVideo", return_value=video
    ), patch.object(
        DownscaleReview, "_move"
    ):
        error = DownscaleReview(DOC_ID).accept()

    assert error is None
    assert (
        video.json_data["downscale"]["ffmpeg_args"]
        == PENDING_JOB["ffmpeg_args"]
    )
    assert video.json_data["downscale"]["encoder"] == "h264"


def test_accept_preserves_missing_ffmpeg_args_as_none():
    """a job accepted before this field existed has nothing to copy"""
    job = {**PENDING_JOB}
    del job["ffmpeg_args"]
    video = _mock_video({"media_url": "video1.mp4"})

    with patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch.object(DownscaleInteract, "delete_item"), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale.YoutubeVideo", return_value=video
    ), patch.object(
        DownscaleReview, "_move"
    ):
        error = DownscaleReview(DOC_ID).accept()

    assert error is None
    assert video.json_data["downscale"]["ffmpeg_args"] is None
