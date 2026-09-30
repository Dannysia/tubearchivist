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

REMOTE_RUNNING_JOB = {
    **QUEUED_JOB,
    "status": "running",
    "task_id": "",
    "worker": "gaming-pc",
}


def test_cancel_job_not_found():
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


def test_cancel_deletes_a_never_dispatched_queued_job():
    job = {**QUEUED_JOB, "task_id": ""}
    with patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch.object(DownscaleInteract, "delete_item") as mock_delete, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch(
        "downscale.src.downscale.TaskManager"
    ) as mock_task_manager:
        error = DownscaleReview(DOC_ID).cancel()

    assert error is None
    mock_delete.assert_called_once()
    mock_task_manager.assert_not_called()
    mock_task_command.return_value.stop.assert_not_called()


def test_cancel_stops_and_immediately_deletes_a_queued_job():
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


def test_cancel_sets_stop_requested_for_a_remote_held_job():
    with patch.object(
        DownscaleInteract, "get_item", return_value=(REMOTE_RUNNING_JOB, 200)
    ), patch.object(DownscaleInteract, "update") as mock_update, patch.object(
        DownscaleInteract, "delete_item"
    ) as mock_delete, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch(
        "downscale.src.downscale.TaskManager"
    ) as mock_task_manager:
        error = DownscaleReview(DOC_ID).cancel()

    assert error is None
    mock_update.assert_called_once_with(stop_requested=True)
    mock_delete.assert_not_called()
    mock_task_command.assert_not_called()
    mock_task_manager.assert_not_called()


def test_cancel_of_a_queued_never_claimed_job_ignores_the_worker_branch():
    job = {**QUEUED_JOB, "task_id": "", "worker": ""}
    with patch.object(
        DownscaleInteract, "get_item", return_value=(job, 200)
    ), patch.object(DownscaleInteract, "delete_item") as mock_delete, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command:
        error = DownscaleReview(DOC_ID).cancel()

    assert error is None
    mock_delete.assert_called_once()
    mock_task_command.return_value.stop.assert_not_called()
