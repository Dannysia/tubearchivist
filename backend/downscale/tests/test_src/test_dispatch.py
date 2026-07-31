"""
tests for dispatch_pending_downscales() - the event-driven replacement
for having every queued job poll a timer asking "is a slot free yet?".
Queuing a job no longer dispatches a celery task by itself; this
function is what actually decides whether/how many to dispatch, called
from every place slot availability could have changed.
"""

from unittest.mock import MagicMock, patch

from downscale.src.downscale import dispatch_pending_downscales
from downscale.src.queue_interact import DownscaleInteract

JOB_A = {"id": "doc-a", "youtube_id": "video-a", "target_height": 480}
JOB_B = {"id": "doc-b", "youtube_id": "video-b", "target_height": 480}


def _mock_lock(acquired=True):
    lock = MagicMock()
    lock.acquire.return_value = acquired
    return lock


def test_dispatches_up_to_the_number_of_free_slots():
    """max_concurrent=2, 1 already running -> exactly 1 free slot"""
    with patch(
        "downscale.src.downscale.RedisBase"
    ) as mock_redis_base, patch(
        "downscale.src.downscale.AppConfig"
    ) as mock_app_config, patch.object(
        DownscaleInteract, "count_running", return_value=1
    ), patch.object(
        DownscaleInteract, "get_next_queued", return_value=[JOB_A]
    ) as mock_get_next, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch.object(
        DownscaleInteract, "update"
    ) as mock_update:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()
        mock_app_config.return_value.config = {
            "application": {"downscale_max_concurrent": 2}
        }
        mock_task_command.return_value.start.return_value = {
            "task_id": "new-task-id"
        }

        dispatch_pending_downscales()

    mock_get_next.assert_called_once_with(1)
    mock_task_command.return_value.start.assert_called_once_with(
        "downscale_video",
        {
            "youtube_id": "video-a",
            "target_height": 480,
            "doc_id": "doc-a",
        },
    )
    mock_update.assert_called_once_with(task_id="new-task-id")


def test_no_free_slots_skips_the_query_entirely():
    """already at the concurrency limit -> don't even ask for queued jobs"""
    with patch(
        "downscale.src.downscale.RedisBase"
    ) as mock_redis_base, patch(
        "downscale.src.downscale.AppConfig"
    ) as mock_app_config, patch.object(
        DownscaleInteract, "count_running", return_value=2
    ), patch.object(
        DownscaleInteract, "get_next_queued"
    ) as mock_get_next, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()
        mock_app_config.return_value.config = {
            "application": {"downscale_max_concurrent": 2}
        }

        dispatch_pending_downscales()

    mock_get_next.assert_not_called()
    mock_task_command.return_value.start.assert_not_called()


def test_unlimited_concurrency_dispatches_everything_queued():
    """downscale_max_concurrent falsy -> no cap, get_next_queued(None)"""
    with patch(
        "downscale.src.downscale.RedisBase"
    ) as mock_redis_base, patch(
        "downscale.src.downscale.AppConfig"
    ) as mock_app_config, patch.object(
        DownscaleInteract, "count_running"
    ) as mock_count_running, patch.object(
        DownscaleInteract, "get_next_queued", return_value=[JOB_A, JOB_B]
    ) as mock_get_next, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command, patch.object(DownscaleInteract, "update"):
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()
        mock_app_config.return_value.config = {
            "application": {"downscale_max_concurrent": None}
        }
        mock_task_command.return_value.start.return_value = {
            "task_id": "new-task-id"
        }

        dispatch_pending_downscales()

    mock_count_running.assert_not_called()
    mock_get_next.assert_called_once_with(None)
    assert mock_task_command.return_value.start.call_count == 2


def test_lock_contention_does_nothing():
    """
    another dispatch already in progress -> back off entirely rather
    than double-dispatch. It'll cover whatever's actually free.
    """
    with patch("downscale.src.downscale.RedisBase") as mock_redis_base, patch(
        "downscale.src.downscale.AppConfig"
    ) as mock_app_config, patch.object(
        DownscaleInteract, "count_running"
    ) as mock_count_running, patch(
        "downscale.src.downscale.TaskCommand"
    ) as mock_task_command:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock(
            acquired=False
        )

        dispatch_pending_downscales()

    mock_app_config.assert_not_called()
    mock_count_running.assert_not_called()
    mock_task_command.return_value.start.assert_not_called()


def test_lock_is_released_even_when_no_slots_are_free():
    """the lock must never be left held on an early return"""
    with patch(
        "downscale.src.downscale.RedisBase"
    ) as mock_redis_base, patch(
        "downscale.src.downscale.AppConfig"
    ) as mock_app_config, patch.object(
        DownscaleInteract, "count_running", return_value=5
    ):
        lock = _mock_lock()
        mock_redis_base.return_value.conn.lock.return_value = lock
        mock_app_config.return_value.config = {
            "application": {"downscale_max_concurrent": 1}
        }

        dispatch_pending_downscales()

    lock.release.assert_called_once()
