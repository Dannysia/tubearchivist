from unittest.mock import Mock, patch

from task.src.task_manager import TaskCommand, TaskManager


def _mock_task(task_id="task-1", name="downscale_video"):
    task = Mock()
    task.name = name
    task.request.id = task_id
    return task


class FakeRedisConn:
    def __init__(self):
        self.store: dict[str, str] = {}

    def execute_command(self, command, *args):
        if command == "SET":
            key, value = args
            self.store[key] = value
        elif command == "GET":
            (key,) = args
            return self.store.get(key)
        elif command == "EXPIRE":
            pass
        elif command == "DEL":
            (key,) = args
            self.store.pop(key, None)
        else:
            raise NotImplementedError(command)


def test_init_sets_initial_pending_message():
    with patch("task.src.task_manager.TaskRedis") as mock_task_redis:
        mock_task_redis.return_value.get_single.return_value = {}
        TaskManager().init(_mock_task())

    message = mock_task_redis.return_value.set_key.call_args.args[1]
    assert message["status"] == "PENDING"
    assert "command" not in message


def test_init_preserves_pending_stop_command():
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
    with patch("task.src.task_manager.TaskRedis") as mock_task_redis:
        mock_task_redis.return_value.get_single.return_value = {
            "status": "PENDING",
            "command": None,
        }
        TaskManager().init(_mock_task())

    message = mock_task_redis.return_value.set_key.call_args.args[1]
    assert "command" not in message


def test_stop_signal_survives_a_retry_reentry():
    fake_conn = FakeRedisConn()
    task = _mock_task(task_id="task-1")

    with patch("common.src.ta_redis.redis.from_url", return_value=fake_conn):
        manager = TaskManager()
        manager.init(task)  # first run

        assert manager.is_stopped("task-1") is False

        TaskCommand().stop("task-1")  # user cancels while it's retrying

        manager.init(task)  # retry re-entry

        assert manager.is_stopped("task-1") is True
