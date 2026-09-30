from common.src.log import LevelType, write_log
from task.src.task_config import get_task_config

EVENT_LEVELS: dict[str, LevelType] = {
    "completed": "info",
    "failed": "error",
    "notified": "info",
    "notify_failed": "error",
}


def log_task_event(task, event: str, message: str) -> None:
    # pylint: disable=broad-except
    try:
        config = get_task_config(task.name)
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
