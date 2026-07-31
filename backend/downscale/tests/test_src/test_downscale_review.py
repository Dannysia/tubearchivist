"""tests for retrying a failed downscale job"""

from unittest.mock import patch

from downscale.src.downscale import DownscaleReview
from downscale.src.queue_interact import DownscaleInteract

DOC_ID = "abc123"

FAILED_JOB = {
    "youtube_id": "video1",
    "target_height": 720,
    "status": "failed",
    "tmp_file_path": "/cache/downscale/video1_720p.mp4",
}


def test_retry_job_not_found():
    """retrying a doc that no longer exists reports an error"""
    with patch.object(
        DownscaleInteract, "get_item", return_value=(None, 404)
    ), patch.object(DownscaleInteract, "update") as mock_update:
        error = DownscaleReview(DOC_ID).retry()

    assert error == "job not found"
    mock_update.assert_not_called()


def test_retry_job_not_failed():
    """retrying a job that isn't in failed status is rejected"""
    job = {**FAILED_JOB, "status": "pending_review"}
    with patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update:
        error = DownscaleReview(DOC_ID).retry()

    assert error == "job is not failed, status is pending_review"
    mock_update.assert_not_called()


def test_retry_requeues_failed_job():
    """
    a failed job's doc is reset to queued with no task_id - it no
    longer dispatches a celery task itself. Callers (the bulk action
    view, ta_startup's auto-resume) are responsible for calling
    dispatch_pending_downscales() once after they're done requeueing,
    so a batch retry doesn't dispatch once per job
    """
    with patch.object(
        DownscaleInteract, "get_item", return_value=(FAILED_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update, patch(
        "downscale.src.downscale.os.path.exists", return_value=False
    ):
        error = DownscaleReview(DOC_ID).retry()

    assert error is None
    mock_update.assert_called_once()
    kwargs = mock_update.call_args.kwargs
    assert kwargs["status"] == "queued"
    assert kwargs["message"] is None
    assert kwargs["task_id"] == ""


def test_retry_cleans_up_leftover_tmp_file():
    """a leftover tmp file from the failed attempt is removed before retry"""
    with patch.object(
        DownscaleInteract, "get_item", return_value=(FAILED_JOB, 200)
    ), patch.object(DownscaleInteract, "update"), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale.os.remove"
    ) as mock_remove:
        DownscaleReview(DOC_ID).retry()

    mock_remove.assert_called_once_with(FAILED_JOB["tmp_file_path"])


def test_requeue_works_on_queued_or_running_job():
    """
    requeue() itself doesn't gate on status - ta_startup's auto-resume
    calls it directly on queued/running leftovers, bypassing retry()'s
    failed-only check
    """
    job = {**FAILED_JOB, "status": "running"}
    with patch.object(DownscaleInteract, "update") as mock_update, patch(
        "downscale.src.downscale.os.path.exists", return_value=False
    ):
        DownscaleReview(DOC_ID).requeue(job)

    mock_update.assert_called_once()
    kwargs = mock_update.call_args.kwargs
    assert kwargs["status"] == "queued"
    assert kwargs["message"] is None
    assert kwargs["task_id"] == ""
