"""tests for retrying a failed downscale job"""

from unittest.mock import Mock, patch

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
    ), patch("downscale.src.downscale.TaskCommand") as mock_task_command:
        error = DownscaleReview(DOC_ID).retry()

    assert error == "job not found"
    mock_task_command.assert_not_called()


def test_retry_job_not_failed():
    """retrying a job that isn't in failed status is rejected"""
    job = {**FAILED_JOB, "status": "pending_review"}
    with patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch("downscale.src.downscale.TaskCommand") as mock_task_command:
        error = DownscaleReview(DOC_ID).retry()

    assert error == "job is not failed, status is pending_review"
    mock_task_command.assert_not_called()


def test_retry_requeues_failed_job():
    """
    a failed job gets a fresh celery task dispatched with its original
    youtube_id/target_height, and its doc is reset to queued

    the doc must flip to queued *before* the task is dispatched, same as
    a fresh job: otherwise a worker that picks up the task immediately
    can write a later status (e.g. failed, on a fast re-fail) that then
    gets clobbered back to "queued" by a trailing update
    """
    with patch.object(
        DownscaleInteract, "get_item", return_value=(FAILED_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update, patch(
        "downscale.src.downscale.os.path.exists", return_value=False
    ), patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command:
        mock_task_command.return_value.start.return_value = {
            "task_id": "new-task-id",
            "status": "PENDING",
            "task_name": "downscale_video",
        }

        manager = Mock()
        manager.attach_mock(mock_update, "update")
        manager.attach_mock(mock_task_command.return_value.start, "start")

        error = DownscaleReview(DOC_ID).retry()

    assert error is None
    mock_task_command.return_value.start.assert_called_once_with(
        "downscale_video",
        {
            "youtube_id": "video1",
            "target_height": 720,
            "doc_id": DOC_ID,
        },
    )

    assert mock_update.call_count == 2
    first_kwargs = mock_update.call_args_list[0].kwargs
    assert first_kwargs["status"] == "queued"
    assert first_kwargs["message"] is None

    second_kwargs = mock_update.call_args_list[1].kwargs
    assert second_kwargs == {"task_id": "new-task-id"}

    assert [call[0] for call in manager.mock_calls] == [
        "update",
        "start",
        "update",
    ]


def test_retry_cleans_up_leftover_tmp_file():
    """a leftover tmp file from the failed attempt is removed before retry"""
    with patch.object(
        DownscaleInteract, "get_item", return_value=(FAILED_JOB, 200)
    ), patch.object(DownscaleInteract, "update"), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.downscale.os.remove"
    ) as mock_remove, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command:
        mock_task_command.return_value.start.return_value = {
            "task_id": "new-task-id",
            "status": "PENDING",
            "task_name": "downscale_video",
        }

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
    ), patch("downscale.src.downscale.TaskCommand") as mock_task_command:
        mock_task_command.return_value.start.return_value = {
            "task_id": "resumed-task-id",
            "status": "PENDING",
            "task_name": "downscale_video",
        }

        DownscaleReview(DOC_ID).requeue(job)

    assert mock_update.call_count == 2
    assert mock_update.call_args_list[0].kwargs["status"] == "queued"
    assert mock_update.call_args_list[1].kwargs == {
        "task_id": "resumed-task-id"
    }
