from unittest.mock import MagicMock, patch

from common.src.es_connect import IndexWriteError
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


def _mock_video(json_data, streams=None):
    video = MagicMock()
    video.json_data = json_data

    def add_streams(media_path=False):
        video.json_data["streams"] = (
            [{"type": "video", "index": 0}] if streams is None else streams
        )

    video.add_streams.side_effect = add_streams

    return video


def test_accept_copies_ffmpeg_args_onto_the_video():
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


def test_accept_probes_the_encode_and_not_the_moved_file():
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
    video.add_streams.assert_called_once_with(
        media_path=PENDING_JOB["tmp_file_path"]
    )
    video.upload_to_es.assert_called_once_with(checked=True)


def test_an_unprobeable_encode_never_replaces_the_original():
    video = _mock_video({"media_url": "video1.mp4"}, streams=[])

    with patch.object(
        DownscaleInteract, "get_item", return_value=(PENDING_JOB, 200)
    ), patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale.YoutubeVideo", return_value=video
    ), patch.object(
        DownscaleReview, "_move"
    ) as mock_move:
        error = DownscaleReview(DOC_ID).accept()

    assert error == "the encode could not be probed"
    mock_move.assert_not_called()
    video.upload_to_es.assert_not_called()
    mock_delete.assert_not_called()
    assert mock_update.call_args.kwargs["status"] == "failed"


def test_the_probe_happens_before_the_move():
    order = []
    video = _mock_video({"media_url": "video1.mp4"})

    def probe(media_path=False):
        order.append("probe")
        video.json_data["streams"] = [{"type": "video"}]

    video.add_streams.side_effect = probe

    with patch.object(
        DownscaleInteract, "get_item", return_value=(PENDING_JOB, 200)
    ), patch.object(DownscaleInteract, "delete_item"), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale.YoutubeVideo", return_value=video
    ), patch.object(
        DownscaleReview, "_move", side_effect=lambda *a: order.append("move")
    ):
        DownscaleReview(DOC_ID).accept()

    assert order == ["probe", "move"]


def test_a_failed_index_write_keeps_the_job_and_reports_it():
    video = _mock_video({"media_url": "video1.mp4"})

    def only_when_checked(checked=False):
        if checked:
            raise IndexWriteError("es answered 503")

    video.upload_to_es.side_effect = only_when_checked

    with patch.object(
        DownscaleInteract, "get_item", return_value=(PENDING_JOB, 200)
    ), patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale.YoutubeVideo", return_value=video
    ), patch.object(
        DownscaleReview, "_move"
    ):
        error = DownscaleReview(DOC_ID).accept()

    assert error == "file replaced but the index was not updated"
    mock_delete.assert_not_called()
    assert mock_update.call_args.kwargs["status"] == "failed"
    assert "503" in mock_update.call_args.kwargs["message"]
