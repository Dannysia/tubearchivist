"""tests for task state/command handling"""

from unittest.mock import Mock, patch

from task.src.task_manager import TaskManager


def _mock_task(task_id="task-1", name="downscale_video"):
    task = Mock()
    task.name = name
    task.request.id = task_id
    return task


def test_init_sets_initial_pending_message():
    """first-ever init writes a fresh PENDING message, no command"""
    with patch("task.src.task_manager.TaskRedis") as mock_task_redis:
        mock_task_redis.return_value.get_single.return_value = {}
        TaskManager().init(_mock_task())

    message = mock_task_redis.return_value.set_key.call_args.args[1]
    assert message["status"] == "PENDING"
    assert "command" not in message


def test_init_preserves_pending_stop_command():
    """
    a task that retries internally (e.g. waiting on a concurrency limit)
    re-runs init() on every retry re-entry - a STOP requested in between
    retries must survive that, or the task will never notice it was
    told to stop
    """
    with patch("task.src.task_manager.TaskRedis") as mock_task_redis:
        mock_task_redis.return_value.get_single.return_value = {
            "status": "RETRY",
            "command": "STOP",
            "retries": 3,
        }
        TaskManager().init(_mock_task())

    message = mock_task_redis.return_value.set_key.call_args.args[1]
    assert message["status"] == "PENDING"
    assert message["command"] == "STOP"


def test_init_does_not_invent_a_command():
    """no command set previously means no command field gets added"""
    with patch("task.src.task_manager.TaskRedis") as mock_task_redis:
        mock_task_redis.return_value.get_single.return_value = {
            "status": "PENDING",
            "command": None,
        }
        TaskManager().init(_mock_task())

    message = mock_task_redis.return_value.set_key.call_args.args[1]
    assert "command" not in message
