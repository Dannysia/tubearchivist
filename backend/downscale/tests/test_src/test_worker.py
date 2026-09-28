from unittest.mock import MagicMock, mock_open, patch

from common.src.queue_interact import QueueWriteError
from downscale.src import worker
from downscale.src.queue_interact import DownscaleInteract

WORKER = "gaming-pc"
DOC_ID = "doc1"

RUNNING_JOB = {
    "youtube_id": "video1",
    "title": "a title",
    "status": "running",
    "worker": WORKER,
    "target_height": 720,
    "tmp_file_path": "/cache/downscale/video1_720p.mp4",
    "stop_requested": False,
}


def _mock_lock(acquired=True):
    lock = MagicMock()
    lock.acquire.return_value = acquired
    return lock


def test_claim_lock_contention_returns_none():
    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_next_queued"
    ) as mock_get_next:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock(
            acquired=False
        )

        result = worker.claim(WORKER)

    assert result is None
    mock_get_next.assert_not_called()


def test_claim_nothing_queued_returns_none():
    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_next_queued", return_value=[]
    ):
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()

        result = worker.claim(WORKER)

    assert result is None


def test_claim_skips_invalid_candidates_and_claims_the_next_valid_one():
    gone_job = {
        "id": "doc-gone",
        "youtube_id": "video-gone",
        "target_height": 480,
        "title": "gone",
        "tmp_file_path": "/cache/downscale/video-gone_480p.mp4",
    }
    good_job = {
        "id": "doc-good",
        "youtube_id": "video-good",
        "target_height": 480,
        "title": "good",
        "tmp_file_path": "/cache/downscale/video-good_480p.mp4",
    }

    missing_video = MagicMock()
    missing_video.json_data = None
    good_video = MagicMock()
    good_video.json_data = {"media_url": "video-good.mp4"}

    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract,
        "get_next_queued",
        return_value=[gone_job, good_job],
    ), patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch.object(
        DownscaleInteract, "get_active_for_video", return_value=None
    ), patch(
        "downscale.src.worker.YoutubeVideo",
        side_effect=[missing_video, good_video],
    ), patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.makedirs"
    ), patch(
        "downscale.src.worker._get_height", return_value=1080
    ), patch(
        "downscale.src.worker.MediaStreamExtractor"
    ) as mock_extractor, patch(
        "downscale.src.worker.AppConfig"
    ) as mock_app_config:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()
        mock_extractor.return_value.get_file_size.return_value = 5000
        mock_app_config.return_value.config = {
            "application": {"downscale_crf": 30}
        }

        result = worker.claim(WORKER)

    mock_delete.assert_called_once()
    assert mock_update.call_args.kwargs["worker"] == WORKER
    assert result == {
        "id": "doc-good",
        "youtube_id": "video-good",
        "title": "good",
        "target_height": 480,
        "quality_hint": 30,
        "source_url": "/youtube/video-good.mp4",
    }


def test_claim_fails_candidate_when_source_file_missing():
    job = {
        "id": "doc1",
        "youtube_id": "video1",
        "target_height": 480,
        "title": "t",
        "tmp_file_path": "/cache/downscale/video1_480p.mp4",
    }
    video = MagicMock()
    video.json_data = {"media_url": "video1.mp4"}

    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_next_queued", return_value=[job]
    ), patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.worker.YoutubeVideo", return_value=video
    ), patch(
        "downscale.src.worker.os.path.exists", return_value=False
    ):
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()

        result = worker.claim(WORKER)

    assert result is None
    assert mock_update.call_args.kwargs["status"] == "failed"
    assert "source file missing" in mock_update.call_args.kwargs["message"]


def test_claim_fails_candidate_when_target_height_no_longer_valid():
    job = {
        "id": "doc1",
        "youtube_id": "video1",
        "target_height": 1080,
        "title": "t",
        "tmp_file_path": "/cache/downscale/video1_1080p.mp4",
    }
    video = MagicMock()
    video.json_data = {"media_url": "video1.mp4"}

    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_next_queued", return_value=[job]
    ), patch.object(
        DownscaleInteract, "update"
    ) as mock_update, patch(
        "downscale.src.worker.YoutubeVideo", return_value=video
    ), patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker._get_height", return_value=720
    ):
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()

        result = worker.claim(WORKER)

    assert result is None
    assert mock_update.call_args.kwargs["status"] == "failed"
    assert "target height" in mock_update.call_args.kwargs["message"]


def test_claim_deletes_candidate_with_another_active_job_for_the_video():
    job = {
        "id": "doc1",
        "youtube_id": "video1",
        "target_height": 480,
        "title": "t",
        "tmp_file_path": "/cache/downscale/video1_480p.mp4",
    }
    video = MagicMock()
    video.json_data = {"media_url": "video1.mp4"}

    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_next_queued", return_value=[job]
    ), patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch.object(
        DownscaleInteract,
        "get_active_for_video",
        return_value={"id": "other-doc"},
    ), patch(
        "downscale.src.worker.YoutubeVideo", return_value=video
    ), patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker._get_height", return_value=1080
    ):
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()

        result = worker.claim(WORKER)

    assert result is None
    mock_delete.assert_called_once()


def test_claim_defaults_quality_hint_when_unset():
    job = {
        "id": "doc1",
        "youtube_id": "video1",
        "target_height": 480,
        "title": "t",
        "tmp_file_path": "/cache/downscale/video1_480p.mp4",
    }
    video = MagicMock()
    video.json_data = {"media_url": "video1.mp4"}

    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_next_queued", return_value=[job]
    ), patch.object(
        DownscaleInteract, "update"
    ), patch.object(
        DownscaleInteract, "get_active_for_video", return_value=None
    ), patch(
        "downscale.src.worker.YoutubeVideo", return_value=video
    ), patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.makedirs"
    ), patch(
        "downscale.src.worker._get_height", return_value=1080
    ), patch(
        "downscale.src.worker.MediaStreamExtractor"
    ) as mock_extractor, patch(
        "downscale.src.worker.AppConfig"
    ) as mock_app_config:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()
        mock_extractor.return_value.get_file_size.return_value = 5000
        mock_app_config.return_value.config = {
            "application": {"downscale_crf": None}
        }

        result = worker.claim(WORKER)

    assert result["quality_hint"] == 23


def test_own_job_not_found():
    with patch.object(DownscaleInteract, "get_item", return_value=(None, 404)):
        job, error = worker._own_job(DOC_ID, WORKER)

    assert job is None
    assert error == "job not found"


def test_own_job_rejects_wrong_worker():
    job = {**RUNNING_JOB, "worker": "someone-else"}
    with patch.object(DownscaleInteract, "get_item", return_value=(job, 200)):
        result_job, error = worker._own_job(DOC_ID, WORKER)

    assert result_job is None
    assert error == worker.NOT_HELD_ERROR


def test_own_job_rejects_non_running_status():
    job = {**RUNNING_JOB, "status": "queued"}
    with patch.object(DownscaleInteract, "get_item", return_value=(job, 200)):
        result_job, error = worker._own_job(DOC_ID, WORKER)

    assert result_job is None
    assert error == worker.NOT_HELD_ERROR


def test_own_job_succeeds_for_the_owning_worker():
    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ):
        result_job, error = worker._own_job(DOC_ID, WORKER)

    assert result_job == RUNNING_JOB
    assert error is None


def test_heartbeat_rejects_when_not_owned():
    with patch.object(DownscaleInteract, "get_item", return_value=(None, 404)):
        result, error = worker.heartbeat(DOC_ID, WORKER, 0.5)

    assert result is None
    assert error == "job not found"


def test_heartbeat_updates_progress_and_reports_no_stop():
    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update:
        result, error = worker.heartbeat(DOC_ID, WORKER, 0.42)

    assert error is None
    assert result == {"stop": False}
    assert mock_update.call_args.kwargs["progress"] == 0.42


def test_heartbeat_reports_stop_when_stop_requested():
    job = {**RUNNING_JOB, "stop_requested": True}
    with patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch.object(DownscaleInteract, "update"):
        result, error = worker.heartbeat(DOC_ID, WORKER, 0.1)

    assert error is None
    assert result == {"stop": True}


def test_upload_result_rejects_when_not_owned():
    with patch.object(DownscaleInteract, "get_item", return_value=(None, 404)):
        error = worker.upload_result(DOC_ID, WORKER, MagicMock())

    assert error == "job not found"


def test_upload_result_streams_to_part_then_renames_into_place():
    stream = MagicMock()

    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch("downscale.src.worker.os.makedirs"), patch(
        "downscale.src.worker.open", mock_open()
    ) as mock_file, patch(
        "downscale.src.worker.shutil.copyfileobj"
    ) as mock_copy, patch(
        "downscale.src.worker.os.replace"
    ) as mock_replace:
        error = worker.upload_result(DOC_ID, WORKER, stream)

    assert error is None
    mock_file.assert_called_once_with(
        f"{RUNNING_JOB['tmp_file_path']}.part", "wb"
    )
    mock_copy.assert_called_once()
    mock_replace.assert_called_once_with(
        f"{RUNNING_JOB['tmp_file_path']}.part", RUNNING_JOB["tmp_file_path"]
    )


def test_upload_result_aborts_without_renaming_if_reclaimed_mid_upload():
    """
    a large upload sends no heartbeat traffic of its own, so it can run
    long enough for a reap to requeue-and-reclaim the doc; the .part is
    then discarded rather than left to clobber the new claim's output
    """
    stream = MagicMock()
    reclaimed_job = {**RUNNING_JOB, "worker": "someone-else"}

    with patch.object(
        DownscaleInteract,
        "get_item",
        side_effect=[(RUNNING_JOB, 200), (reclaimed_job, 200)],
    ), patch("downscale.src.worker.os.makedirs"), patch(
        "downscale.src.worker.open", mock_open()
    ), patch(
        "downscale.src.worker.shutil.copyfileobj"
    ), patch(
        "downscale.src.worker.os.replace"
    ) as mock_replace, patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove:
        error = worker.upload_result(DOC_ID, WORKER, stream)

    assert error == worker.NOT_HELD_ERROR
    mock_replace.assert_not_called()
    mock_remove.assert_called_once_with(f"{RUNNING_JOB['tmp_file_path']}.part")


def test_upload_result_aborts_without_renaming_if_cancelled_mid_upload():
    """the result is discarded even though it is complete and valid"""
    stream = MagicMock()
    cancelled_job = {**RUNNING_JOB, "stop_requested": True}

    with patch.object(
        DownscaleInteract,
        "get_item",
        side_effect=[(RUNNING_JOB, 200), (cancelled_job, 200)],
    ), patch("downscale.src.worker.os.makedirs"), patch(
        "downscale.src.worker.open", mock_open()
    ), patch(
        "downscale.src.worker.shutil.copyfileobj"
    ), patch(
        "downscale.src.worker.os.replace"
    ) as mock_replace, patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove:
        error = worker.upload_result(DOC_ID, WORKER, stream)

    assert error == worker.CANCELLED_ERROR
    mock_replace.assert_not_called()
    mock_remove.assert_called_once_with(f"{RUNNING_JOB['tmp_file_path']}.part")


def test_finish_rejects_when_not_owned():
    with patch.object(DownscaleInteract, "get_item", return_value=(None, 404)):
        error = worker.finish(
            DOC_ID, WORKER, "av1_nvenc", 30, "p5", "ffmpeg …"
        )

    assert error == "job not found"


def test_finish_marks_failed_on_invalid_output():
    """ffmpeg exited cleanly on the worker side but produced junk"""
    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update, patch(
        "downscale.src.worker._get_height", return_value=None
    ), patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        error = worker.finish(
            DOC_ID, WORKER, "av1_nvenc", 30, "p5", "ffmpeg …"
        )

    assert error is None
    mock_remove.assert_called_once_with(RUNNING_JOB["tmp_file_path"])
    kwargs = mock_update.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["worker"] == ""
    mock_dispatch.assert_called_once()


def test_finish_marks_pending_review_and_records_the_report():
    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update, patch(
        "downscale.src.worker._get_height", return_value=720
    ), patch(
        "downscale.src.worker.MediaStreamExtractor"
    ) as mock_extractor, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        mock_extractor.return_value.get_file_size.return_value = 9999

        error = worker.finish(
            DOC_ID, WORKER, "av1_nvenc", 30, "p5", "ffmpeg -y -i … av1_nvenc"
        )

    assert error is None
    kwargs = mock_update.call_args.kwargs
    assert kwargs["status"] == "pending_review"
    assert kwargs["new_size"] == 9999
    assert kwargs["encoder"] == "av1_nvenc"
    assert kwargs["quality"] == 30
    assert kwargs["preset"] == "p5"
    assert kwargs["ffmpeg_args"] == "ffmpeg -y -i … av1_nvenc"
    assert kwargs["worker"] == ""
    mock_dispatch.assert_called_once()


def test_finish_discards_instead_of_pending_review_when_already_cancelled():
    """
    a worker sends no heartbeat during upload/finish, so a cancel can
    race in after its last one: the otherwise-valid result is discarded
    rather than marked done
    """
    cancelled_job = {**RUNNING_JOB, "stop_requested": True}

    with patch.object(
        DownscaleInteract, "get_item", return_value=(cancelled_job, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update, patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch(
        "downscale.src.worker._get_height"
    ) as mock_get_height, patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        error = worker.finish(
            DOC_ID, WORKER, "av1_nvenc", 30, "p5", "ffmpeg …"
        )

    assert error is None
    mock_get_height.assert_not_called()
    mock_update.assert_not_called()
    mock_delete.assert_called_once()
    assert mock_remove.call_count == 2
    mock_dispatch.assert_called_once()


def test_fail_rejects_when_not_owned():
    with patch.object(DownscaleInteract, "get_item", return_value=(None, 404)):
        error = worker.fail(DOC_ID, WORKER, "boom")

    assert error == "job not found"


def test_fail_marks_failed_and_clears_worker():
    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update:
        error = worker.fail(DOC_ID, WORKER, "stderr tail")

    assert error is None
    kwargs = mock_update.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["message"] == "stderr tail"
    assert kwargs["worker"] == ""


def test_fail_truncates_an_overlong_message_like_the_local_runner_does():
    long_message = "x" * 3000

    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update:
        worker.fail(DOC_ID, WORKER, long_message)

    stored = mock_update.call_args.kwargs["message"]
    assert len(stored) == 2000
    assert stored == long_message[-2000:]


def test_fail_discards_instead_of_failed_when_already_cancelled():
    """not a failed doc left around for a retry nobody asked for"""
    cancelled_job = {**RUNNING_JOB, "stop_requested": True}

    with patch.object(
        DownscaleInteract, "get_item", return_value=(cancelled_job, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update, patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        error = worker.fail(DOC_ID, WORKER, "stderr tail")

    assert error is None
    mock_update.assert_not_called()
    mock_delete.assert_called_once()
    assert mock_remove.call_count == 2
    mock_dispatch.assert_called_once()


def test_delete_rejects_when_not_owned():
    with patch.object(DownscaleInteract, "get_item", return_value=(None, 404)):
        error = worker.delete(DOC_ID, WORKER)

    assert error == "job not found"


def test_delete_cleans_up_tmp_files_and_dispatches():
    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "delete_item") as mock_delete, patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        error = worker.delete(DOC_ID, WORKER)

    assert error is None
    assert mock_remove.call_count == 2
    mock_delete.assert_called_once()
    mock_dispatch.assert_called_once()


def test_reap_no_stale_leases_does_nothing():
    with patch.object(
        DownscaleInteract, "get_stale_leases", return_value=[]
    ), patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        worker.reap_stale_leases()

    mock_dispatch.assert_not_called()


def test_reap_requeues_a_stale_lease_and_clears_every_remote_field():
    """
    every remote field is cleared, not just status: the local-only
    count_running/get_interrupted filters key off worker==""
    """
    stale_job = {
        "id": "doc1",
        "tmp_file_path": "/cache/downscale/video1_720p.mp4",
        "stop_requested": False,
    }
    with patch.object(
        DownscaleInteract, "get_stale_leases", return_value=[stale_job]
    ), patch.object(DownscaleInteract, "update") as mock_update, patch(
        "downscale.src.worker.os.path.exists", return_value=False
    ), patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        worker.reap_stale_leases()

    kwargs = mock_update.call_args.kwargs
    assert kwargs["status"] == "queued"
    assert kwargs["task_id"] == ""
    assert kwargs["worker"] == ""
    assert kwargs["last_heartbeat"] == 0
    assert kwargs["progress"] == 0.0
    assert kwargs["stop_requested"] is False
    mock_dispatch.assert_called_once()


def test_reap_requeue_also_cleans_up_a_leftover_part_file():
    """
    the .part sibling belongs to the expired lease too, and must not
    survive to collide with whoever claims this job next
    """
    stale_job = {
        "id": "doc1",
        "tmp_file_path": "/cache/downscale/video1_720p.mp4",
        "stop_requested": False,
    }
    with patch.object(
        DownscaleInteract, "get_stale_leases", return_value=[stale_job]
    ), patch.object(DownscaleInteract, "update"), patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ):
        worker.reap_stale_leases()

    assert mock_remove.call_count == 2
    mock_remove.assert_any_call(stale_job["tmp_file_path"])
    mock_remove.assert_any_call(f"{stale_job['tmp_file_path']}.part")


def test_reap_deletes_a_stale_lease_with_stop_requested():
    """cancelled before the worker died: delete rather than requeue"""
    stale_job = {
        "id": "doc1",
        "tmp_file_path": "/cache/downscale/video1_720p.mp4",
        "stop_requested": True,
    }
    with patch.object(
        DownscaleInteract, "get_stale_leases", return_value=[stale_job]
    ), patch.object(DownscaleInteract, "update") as mock_update, patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch(
        "downscale.src.worker.os.path.exists", return_value=True
    ), patch(
        "downscale.src.worker.os.remove"
    ) as mock_remove, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        worker.reap_stale_leases()

    mock_update.assert_not_called()
    mock_delete.assert_called_once()
    assert mock_remove.call_count == 2
    mock_dispatch.assert_called_once()


def test_claim_skips_a_candidate_whose_write_fails():
    jobs = [{"id": "doc-bad"}, {"id": "doc-good"}]
    claimed = {"id": "doc-good", "youtube_id": "video2"}

    with patch(
        "downscale.src.worker.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_next_queued", return_value=jobs
    ), patch.object(
        worker,
        "_try_claim_candidate",
        side_effect=[QueueWriteError("es down"), claimed],
    ):
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()

        result = worker.claim(WORKER)

    assert result == claimed


def test_reap_continues_past_a_job_whose_write_fails():
    stale = [
        {"id": "doc-bad", "tmp_file_path": None, "stop_requested": False},
        {"id": "doc-good", "tmp_file_path": None, "stop_requested": False},
    ]

    with patch.object(
        DownscaleInteract, "get_stale_leases", return_value=stale
    ), patch.object(
        DownscaleInteract,
        "update",
        side_effect=[QueueWriteError("es down"), None],
    ) as mock_update, patch(
        "downscale.src.worker.dispatch_pending_downscales"
    ) as mock_dispatch:
        worker.reap_stale_leases()

    assert mock_update.call_count == 2
    mock_dispatch.assert_called_once()
