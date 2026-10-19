from contextlib import ExitStack, contextmanager
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


@contextmanager
def _accepting(video, job=PENDING_JOB, verify_error=None, replace=None):
    mocks = {}
    with ExitStack() as stack:
        stack.enter_context(patch("downscale.src.downscale.RedisBase"))
        stack.enter_context(
            patch.object(
                DownscaleInteract, "get_item", return_value=(job, 200)
            )
        )
        mocks["delete"] = stack.enter_context(
            patch.object(DownscaleInteract, "delete_item")
        )
        mocks["update"] = stack.enter_context(
            patch.object(DownscaleInteract, "update")
        )
        stack.enter_context(
            patch("downscale.src.downscale.os.path.exists", return_value=True)
        )
        stack.enter_context(
            patch("downscale.src.downscale.YoutubeVideo", return_value=video)
        )
        mocks["verify"] = stack.enter_context(
            patch(
                "downscale.src.downscale.verify_encode",
                return_value=verify_error,
            )
        )
        mocks["replace"] = stack.enter_context(
            patch.object(
                DownscaleReview,
                "_replace",
                return_value="/youtube/.abc123.downscale-backup",
                side_effect=replace,
            )
        )
        mocks["remove"] = stack.enter_context(
            patch("downscale.src.downscale._remove_quietly")
        )
        mocks["os_replace"] = stack.enter_context(
            patch("downscale.src.downscale.os.replace")
        )
        yield mocks


def test_accept_copies_ffmpeg_args_onto_the_video():
    video = _mock_video({"media_url": "video1.mp4"})

    with _accepting(video):
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

    with _accepting(video, job=job):
        error = DownscaleReview(DOC_ID).accept()

    assert error is None
    assert video.json_data["downscale"]["ffmpeg_args"] is None


def test_accept_probes_the_encode_and_not_the_moved_file():
    video = _mock_video({"media_url": "video1.mp4"})

    with _accepting(video):
        error = DownscaleReview(DOC_ID).accept()

    assert error is None
    video.add_streams.assert_called_once_with(
        media_path=PENDING_JOB["tmp_file_path"]
    )
    video.upload_to_es.assert_called_once_with(checked=True)


def test_a_successful_accept_cleans_up_the_backup_and_the_encode():
    video = _mock_video({"media_url": "video1.mp4"})

    with _accepting(video) as mocks:
        DownscaleReview(DOC_ID).accept()

    removed = [call.args[0] for call in mocks["remove"].call_args_list]
    assert removed == [
        "/youtube/.abc123.downscale-backup",
        PENDING_JOB["tmp_file_path"],
    ]
    mocks["delete"].assert_called_once()


def test_an_unprobeable_encode_never_replaces_the_original():
    video = _mock_video({"media_url": "video1.mp4"}, streams=[])

    with _accepting(video) as mocks:
        error = DownscaleReview(DOC_ID).accept()

    assert error == "the encode could not be probed"
    mocks["replace"].assert_not_called()
    video.upload_to_es.assert_not_called()
    mocks["delete"].assert_not_called()
    assert mocks["update"].call_args.kwargs["status"] == "failed"


def test_a_failed_verification_never_replaces_the_original():
    video = _mock_video({"media_url": "video1.mp4"})

    with _accepting(
        video, verify_error="the encode is truncated, original kept"
    ) as mocks:
        error = DownscaleReview(DOC_ID).accept()

    assert error == "the encode is truncated, original kept"
    mocks["verify"].assert_called_once_with(
        PENDING_JOB["tmp_file_path"], "/youtube/video1.mp4", 1000
    )
    mocks["replace"].assert_not_called()
    mocks["delete"].assert_not_called()
    assert mocks["update"].call_args.kwargs["status"] == "failed"


def test_the_probe_happens_before_the_move():
    order = []
    video = _mock_video({"media_url": "video1.mp4"})

    def probe(media_path=False):
        order.append("probe")
        video.json_data["streams"] = [{"type": "video"}]

    video.add_streams.side_effect = probe

    def replace(*args):
        order.append("move")
        return "/youtube/.abc123.downscale-backup"

    with _accepting(video, replace=replace):
        DownscaleReview(DOC_ID).accept()

    assert order == ["probe", "move"]


def test_a_failed_replace_keeps_the_job_for_another_try():
    video = _mock_video({"media_url": "video1.mp4"})

    with _accepting(
        video, replace=OSError(28, "No space left on device")
    ) as mocks:
        error = DownscaleReview(DOC_ID).accept()

    assert error.startswith("could not replace the original, original kept")
    video.upload_to_es.assert_not_called()
    mocks["delete"].assert_not_called()
    mocks["update"].assert_not_called()


def test_a_failed_index_write_restores_the_original_and_keeps_the_job():
    video = _mock_video({"media_url": "video1.mp4"})

    def only_when_checked(checked=False):
        if checked:
            raise IndexWriteError("es answered 503")

    video.upload_to_es.side_effect = only_when_checked

    with _accepting(video) as mocks:
        error = DownscaleReview(DOC_ID).accept()

    assert error == "the index was not updated, original kept: es answered 503"
    mocks["os_replace"].assert_called_once_with(
        "/youtube/.abc123.downscale-backup", "/youtube/video1.mp4"
    )
    mocks["delete"].assert_not_called()
    mocks["update"].assert_not_called()
    mocks["remove"].assert_not_called()


def test_a_failed_restore_marks_the_job_failed_with_the_backup_path():
    video = _mock_video({"media_url": "video1.mp4"})
    video.upload_to_es.side_effect = IndexWriteError("es answered 503")

    with _accepting(video) as mocks:
        mocks["os_replace"].side_effect = OSError("read-only file system")
        error = DownscaleReview(DOC_ID).accept()

    assert error == (
        "the index was not updated and the original could not be restored"
    )
    message = mocks["update"].call_args.kwargs["message"]
    assert mocks["update"].call_args.kwargs["status"] == "failed"
    assert "/youtube/.abc123.downscale-backup" in message


def test_a_held_lock_refuses_a_second_accept():
    video = _mock_video({"media_url": "video1.mp4"})

    with _accepting(video) as mocks, patch(
        "downscale.src.downscale.RedisBase"
    ) as redis_base:
        redis_base.return_value.conn.lock.return_value.acquire.return_value = (
            False
        )
        error = DownscaleReview(DOC_ID).accept()

    assert error == "this job is already being accepted"
    mocks["replace"].assert_not_called()
