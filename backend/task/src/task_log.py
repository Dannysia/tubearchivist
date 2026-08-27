"""
functionality:
- record what a celery task did, so it survives past the redis toast
- decide which task outcomes are worth a log entry at all

Kept apart from common.src.log so the writer stays free of task
concerns, and out of notify.py so apprise stays free of both.
"""

from common.src.log import LevelType, write_log
from task.src.task_config import TASK_CONFIG

# the level an outcome maps to, so the writer and the UI filter agree
EVENT_LEVELS: dict[str, LevelType] = {
    "completed": "info",
    "failed": "error",
    "notified": "info",
    "notify_failed": "error",
}


def log_task_event(task, event: str, message: str) -> None:
    """
    record one outcome for a running task

    Takes the bound task rather than its pieces so a caller inside a
    BaseTask callback cannot assemble a half filled entry. Never raises,
    for the same reason write_log does not: this runs from celery
    callbacks, where an exception is reported against the task that just
    finished and reads as that task having failed.
    """
    # pylint: disable=broad-except
    try:
        config = TASK_CONFIG.get(task.name) or {}
        write_log(
            source="notification",
            level=EVENT_LEVELS.get(event, "info"),
            message=message,
            event=event,
            task_id=task.request.id,
            task_name=task.name,
            task_title=config.get("title"),
            group=config.get("group"),
        )
    except Exception as err:
        print(f"failed to log task event: {err}")
