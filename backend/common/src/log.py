"""
writing is deliberately best effort: losing a log entry must never take
down the thing being logged about, so write_log() swallows everything
and only prints when it could not write. Celery's own stdout stays the
backstop for anything that happens while ES is unreachable.
"""

from datetime import datetime, timezone
from typing import Literal

from common.src.es_connect import ElasticWrap

INDEX_NAME = "ta_log"

SourceType = Literal["notification", "application"]
LevelType = Literal["info", "error"]

FALLBACK_RETENTION_DAYS = 7
DAY_SECONDS = 86400


def now_epoch() -> int:
    """epoch seconds, matching the index mapping"""
    return int(datetime.now(tz=timezone.utc).timestamp())


def write_log(
    source: SourceType,
    level: LevelType,
    message: str,
    event: str | None = None,
    task_id: str | None = None,
    task_name: str | None = None,
    task_title: str | None = None,
    group: str | None = None,
) -> None:
    """
    never raises: this runs from celery callbacks, where an exception
    would be reported against the task that just finished and read as
    that task having failed
    """
    # pylint: disable=broad-except
    document = {
        "timestamp": now_epoch(),
        "source": source,
        "level": level,
        "message": message,
        "event": event,
        "task_id": task_id,
        "task_name": task_name,
        "task_title": task_title,
        "group": group,
    }
    document = {k: v for k, v in document.items() if v is not None}

    try:
        _, status_code = ElasticWrap(f"{INDEX_NAME}/_doc").post(document)
        if status_code not in [200, 201]:
            print(f"failed to write log entry: {status_code}")
    except Exception as err:
        print(f"failed to write log entry: {err}")


def prune_logs(days: int | None = None) -> int:
    """
    days=0 falls back rather than pruning everything, which is only safe
    because the serializer for the setting has min_value=1 - keep that
    floor if the field ever moves
    """
    retention = days or FALLBACK_RETENTION_DAYS
    cutoff = now_epoch() - retention * DAY_SECONDS
    data = {
        # the explicit format is required: es reads a bare numeric on a
        # date field as epoch millis regardless of the field's own
        # epoch_second format, so an int cutoff matches nothing
        "query": {
            "range": {"timestamp": {"lt": cutoff, "format": "epoch_second"}}
        }
    }
    response, _ = ElasticWrap(f"{INDEX_NAME}/_delete_by_query").post(data)

    return response.get("deleted", 0)


def clear_logs(source: SourceType | None = None) -> int:
    if source:
        query: dict = {"term": {"source": {"value": source}}}
    else:
        query = {"match_all": {}}

    # refresh, unlike prune: the logs page re-reads immediately after
    # this, and without it the deleted entries stay visible and the
    # clear button looks like it did nothing
    response, _ = ElasticWrap(
        f"{INDEX_NAME}/_delete_by_query?refresh=true"
    ).post({"query": query})

    return response.get("deleted", 0)
