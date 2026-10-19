from uuid import uuid4

from common.src.ta_redis import RedisArchivist
from downscale.src.downscale import DownscaleReview
from task.celery import app as celery_app
from task.src.task_manager import TaskManager

BULK_KEY_PREFIX = "downscale:bulk:"
BULK_EXPIRE = 60 * 60 * 24
BULK_ACTIONS = ("accept", "reject")
ACTIVE_STATUSES = ("queued", "running")
DEAD_TASK_STATUSES = ("FAILURE", "FAILED", "REVOKED")


def _write(state: dict) -> None:
    RedisArchivist().set_message(
        f"{BULK_KEY_PREFIX}{state['task_id']}", state, expire=BULK_EXPIRE
    )


def queue_bulk(ids: list[str], action: str) -> dict:
    state = {
        "task_id": str(uuid4()),
        "action": action,
        "total": len(ids),
        "done": 0,
        "failed": [],
        "status": "queued",
        "stopped": False,
        "failure": None,
    }
    _write(state)
    celery_app.send_task(
        "downscale_bulk", args=[ids, action], task_id=state["task_id"]
    )
    return state


def get_bulk(task_id: str) -> dict | None:
    state = RedisArchivist().get_message_dict(f"{BULK_KEY_PREFIX}{task_id}")
    if not state:
        return None

    if state["status"] in ACTIVE_STATUSES:
        task = TaskManager().get_task(task_id)
        if task.get("status") in DEAD_TASK_STATUSES:
            state["status"] = "failed"
            state["failure"] = _task_error(task)

    return state


def _task_error(task: dict) -> str:
    result = task.get("result")
    if not isinstance(result, dict) or not result.get("exc_type"):
        return "the bulk task stopped unexpectedly"

    message = " ".join(str(i) for i in result.get("exc_message") or [])
    if not message:
        return result["exc_type"]

    return f"{result['exc_type']}: {message}"


def get_active_bulk() -> dict | None:
    for key in RedisArchivist().list_keys(BULK_KEY_PREFIX):
        state = get_bulk(key.removeprefix(BULK_KEY_PREFIX))
        if state and state["status"] in ACTIVE_STATUSES:
            return state

    return None


def clear_queued_bulks() -> int:
    redis = RedisArchivist()
    cleared = 0
    for key in redis.list_keys(BULK_KEY_PREFIX):
        state = redis.get_message_dict(key)
        if state and state["status"] == "queued":
            redis.del_message(key)
            cleared += 1

    return cleared


def run_bulk(task, ids: list[str], action: str) -> str:
    state = get_bulk(task.request.id) or {
        "task_id": task.request.id,
        "action": action,
        "total": len(ids),
        "failed": [],
        "stopped": False,
        "failure": None,
    }
    state.update({"status": "running", "done": 0})
    _write(state)

    for doc_id in ids:
        if task.is_stopped():
            state["stopped"] = True
            break

        try:
            error = getattr(DownscaleReview(doc_id), action)()
        except Exception as err:  # pylint: disable=broad-except
            error = f"{type(err).__name__}: {err}"

        if error:
            state["failed"].append({"id": doc_id, "error": error})

        state["done"] += 1
        _write(state)

    state["status"] = "done"
    _write(state)
    return _summary(state)


def _summary(state: dict) -> str:
    failed = len(state["failed"])
    summary = (
        f"Bulk {state['action']}: {state['done'] - failed} of "
        f"{state['total']} jobs succeeded"
    )
    if failed:
        summary += f", {failed} failed"
    if state["stopped"]:
        summary += ", stopped early"

    return summary
