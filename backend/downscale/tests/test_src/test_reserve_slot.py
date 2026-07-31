"""
tests for the downscale dispatch/concurrency-limit retry cadence.

with a large backlog and a low downscale_max_concurrent, most queued
jobs spend their time purely waiting for a running slot to free up -
that only happens on encode completion (at least a minute in practice),
so it shouldn't retry on the same short cadence as transient dispatch-
lock contention between concurrently-dispatching tasks.
"""

from unittest.mock import MagicMock, Mock, patch

from downscale.src.downscale import CONCURRENCY_RETRY_DELAY, DownscaleRunner
from downscale.src.queue_interact import DownscaleInteract


def _make_runner(task):
    return DownscaleRunner(
        task=task, youtube_id="video1", target_height=480, doc_id="doc1"
    )


def _mock_task():
    """
    real celery Task.retry() raises internally - side_effect mirrors
    that so `raise self.task.retry(...)` in the source behaves the same
    way here as it does for real
    """
    task = Mock()
    task.request.id = "task-1"
    task.retry.side_effect = RuntimeError("retry raised")
    return task


def _mock_lock(acquired=True):
    lock = MagicMock()
    lock.acquire.return_value = acquired
    return lock


def test_concurrency_limit_retries_with_longer_countdown():
    """
    blocked purely on downscale_max_concurrent -> use the longer,
    concurrency-specific delay, not the task's short default
    """
    task = _mock_task()
    runner = _make_runner(task)

    with patch(
        "downscale.src.downscale.RedisBase"
    ) as mock_redis_base, patch.object(
        DownscaleInteract, "get_active_for_video", return_value=None
    ), patch.object(
        DownscaleInteract, "count_running", return_value=1
    ), patch(
        "downscale.src.downscale.AppConfig"
    ) as mock_app_config:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock()
        mock_app_config.return_value.config = {
            "application": {"downscale_max_concurrent": 1}
        }

        try:
            runner._reserve_slot(current_height=1080, original_path="/x.mp4")
        except RuntimeError:
            pass

    task.retry.assert_called_once_with(countdown=CONCURRENCY_RETRY_DELAY)


def test_dispatch_lock_contention_uses_default_retry_cadence():
    """
    failing to acquire the dispatch lock is short-lived contention
    between concurrently-dispatching tasks, not "nothing to do for a
    while" - it keeps the task's own short default_retry_delay rather
    than the longer concurrency-limit-specific one
    """
    task = _mock_task()
    runner = _make_runner(task)

    with patch("downscale.src.downscale.RedisBase") as mock_redis_base:
        mock_redis_base.return_value.conn.lock.return_value = _mock_lock(
            acquired=False
        )

        try:
            runner._reserve_slot(current_height=1080, original_path="/x.mp4")
        except RuntimeError:
            pass

    task.retry.assert_called_once_with()
