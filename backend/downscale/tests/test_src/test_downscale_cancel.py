"""
tests for cancelling a queued/running downscale job.

regression coverage for two live bugs found 2026-07-30:
1. a queued job retrying on a concurrency limit calls TaskManager.init()
   on every retry re-entry, which used to silently clobber a pending
   STOP command before the task ever checked is_stopped() - see
   test_task_manager.py for that fix.
2. even once the STOP command survives, a queued job only notices it on
   its own next retry (up to default_retry_delay=20s later), so a large
   batch of cancelled-but-still-queued jobs could sit around for
   minutes. Since a queued job has no process or tmp file yet, its doc
   is now deleted immediately instead of waiting for the task to notice.

These tests cover DownscaleReview.cancel()'s guards (right status, task
actually known to TaskManager before TaskCommand().stop() is called -
TaskRedis.set_command raises KeyError on an unknown task_id) and the
queued-deletes-immediately/running-waits-for-the-task split.
"""

from unittest.mock import patch

from downscale.src.downscale import DownscaleReview
from downscale.src.queue_interact import DownscaleInteract

DOC_ID = "abc123"

QUEUED_JOB = {
    "youtube_id": "video1",
    "target_height": 720,
    "status": "queued",
    "task_id": "task-1",
}

RUNNING_JOB = {**QUEUED_JOB, "status": "running"}


def test_cancel_job_not_found():
    """cancelling a doc that no longer exists reports an error"""
    with patch.object(
        DownscaleInteract, "get_item", return_value=(None, 404)
    ), patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch(
        "downscale.src.downscale.TaskManager"
    ) as mock_task_manager:
        error = DownscaleReview(DOC_ID).cancel()

    assert error == "job not found"
    mock_task_command.assert_not_called()
    mock_task_manager.assert_not_called()


def test_cancel_rejects_non_cancelable_status():
    """
    a job that's already pending_review/failed/cancelled has nothing
    running to stop - reject it rather than silently no-op
    """
    job = {**QUEUED_JOB, "status": "pending_review"}
    with patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch(
        "downscale.src.downscale.TaskManager"
    ) as mock_task_manager:
        error = DownscaleReview(DOC_ID).cancel()

    assert error == "job is not queued or running, status is pending_review"
    mock_task_command.assert_not_called()
    mock_task_manager.assert_not_called()


def test_cancel_stops_and_immediately_deletes_a_queued_job():
    """
    a queued job with a known task sends the real STOP signal *and* its
    doc is deleted right away - it has no process/tmp file yet, so
    there's nothing to lose by not waiting for its own retry to notice
    """
    with patch.object(
        DownscaleInteract, "get_item", return_value=(QUEUED_JOB, 200)
    ), patch.object(DownscaleInteract, "delete_item") as mock_delete, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch(
        "downscale.src.downscale.TaskManager"
    ) as mock_task_manager:
        mock_task_manager.return_value.get_task.return_value = {
            "status": "RETRY"
        }

        error = DownscaleReview(DOC_ID).cancel()

    assert error is None
    mock_task_command.return_value.stop.assert_called_once_with("task-1")
    mock_delete.assert_called_once()


def test_cancel_stops_a_running_job_without_deleting_its_doc():
    """
    a running job sends the real STOP signal but its doc is left alone -
    ffmpeg is still writing to the tmp file, so only the task itself
    (which actually owns that subprocess) can safely terminate it and
    clean up, via its existing poll loop
    """
    with patch.object(
        DownscaleInteract, "get_item", return_value=(RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "delete_item") as mock_delete, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch(
        "downscale.src.downscale.TaskManager"
    ) as mock_task_manager:
        mock_task_manager.return_value.get_task.return_value = {
            "status": "PROGRESS"
        }

        error = DownscaleReview(DOC_ID).cancel()

    assert error is None
    mock_task_command.return_value.stop.assert_called_once_with("task-1")
    mock_delete.assert_not_called()


def test_cancel_fails_gracefully_when_task_not_yet_known():
    """
    a task_id TaskManager has never heard of (not yet started, or a
    stale/synthetic id) must not reach TaskCommand().stop() or delete
    anything - TaskRedis.set_command raises a bare KeyError for an
    unknown task_id, which would otherwise surface as an uncaught 500
    """
    with patch.object(
        DownscaleInteract, "get_item", return_value=(QUEUED_JOB, 200)
    ), patch.object(DownscaleInteract, "delete_item") as mock_delete, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch(
        "downscale.src.downscale.TaskManager"
    ) as mock_task_manager:
        mock_task_manager.return_value.get_task.return_value = {}

        error = DownscaleReview(DOC_ID).cancel()

    assert error == "task not found, may not have started yet"
    mock_task_command.return_value.stop.assert_not_called()
    mock_delete.assert_not_called()
