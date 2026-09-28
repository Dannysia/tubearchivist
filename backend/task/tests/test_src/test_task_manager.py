from unittest.mock import Mock, patch

from task.src.task_manager import TaskCommand, TaskManager


def _mock_task(task_id="task-1", name="downscale_video"):
    task = Mock()
    task.name = name
    task.request.id = task_id
    return task


class FakeRedisConn:
    """
    in-memory stand-in for the subset of redis-py's connection interface
    TaskRedis uses, so the real TaskRedis/TaskManager/TaskCommand
    read-modify-write logic runs instead of being mocked away - one call
    clobbering another's write shows up no other way
    """

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
    """
    a task that retries internally (e.g. waiting on a concurrency limit)
    re-runs init() on every retry re-entry, so a STOP requested in
    between must survive that or the task never notices it
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
    with patch("task.src.task_manager.TaskRedis") as mock_task_redis:
        mock_task_redis.return_value.get_single.return_value = {
            "status": "PENDING",
            "command": None,
        }
        TaskManager().init(_mock_task())

    message = mock_task_redis.return_value.set_key.call_args.args[1]
    assert "command" not in message


def test_stop_signal_survives_a_retry_reentry():
    """
    the whole sequence: init (first run) -> stop() while it is retrying
    -> init() again (the retry re-entry) -> is_stopped() must still see
    it. Only the redis connection is faked, because mocking
    get_single/set_key directly cannot catch a bug that IS the
    interaction between those two calls.
    """
    fake_conn = FakeRedisConn()
    task = _mock_task(task_id="task-1")

    with patch("common.src.ta_redis.redis.from_url", return_value=fake_conn):
        manager = TaskManager()
        manager.init(task)  # first run

        assert manager.is_stopped("task-1") is False

        TaskCommand().stop("task-1")  # user cancels while it's retrying

        manager.init(task)  # retry re-entry

        assert manager.is_stopped("task-1") is True
