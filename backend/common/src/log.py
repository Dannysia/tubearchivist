"""
functionality:
- append events to the ta_log index
- prune entries past the retention window, or clear them outright

Writing is deliberately best effort: losing a log entry must never take
down the thing being logged about, so write_log() swallows everything
and only prints when it could not write. What celery already puts on
stdout stays the backstop for anything that happens while ES itself is
unreachable.
"""

from datetime import datetime, timezone
from typing import Literal

from common.src.es_connect import ElasticWrap

INDEX_NAME = "ta_log"

SourceType = Literal["notification", "application"]
# only the two an outcome can actually be. A third level is a one line
# change here when something needs to write one
LevelType = Literal["info", "error"]

FALLBACK_RETENTION_DAYS = 7
DAY_SECONDS = 86400


def now_epoch() -> int:
    """current time as an epoch second, matching the index mapping"""
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
    append one entry to the log index

    Never raises. This runs from celery callbacks, where an exception
    would be reported against the task that just finished and read as
    that task having failed.
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
    """delete entries older than the retention window, return the count

    A days of 0 falls back rather than pruning everything, which is only
    safe because AppConfigAppSerializer.log_retention_days sets
    min_value=1 - there is no way to store a 0 for this to read. Keep
    that floor if the field ever moves.
    """
    retention = days or FALLBACK_RETENTION_DAYS
    cutoff = now_epoch() - retention * DAY_SECONDS
    data = {
        # the explicit format is required: es reads a bare numeric on a
        # date field as epoch millis regardless of the field's own
        # epoch_second format, so an int cutoff silently matches nothing
        # rather than erroring. Same fix as HistoryQuery.build_query.
        "query": {
            "range": {"timestamp": {"lt": cutoff, "format": "epoch_second"}}
        }
    }
    response, _ = ElasticWrap(f"{INDEX_NAME}/_delete_by_query").post(data)

    return response.get("deleted", 0)


def clear_logs(source: SourceType | None = None) -> int:
    """delete every entry, or every entry from one source"""
    if source:
        query: dict = {"term": {"source": {"value": source}}}
    else:
        query = {"match_all": {}}

    # refresh, unlike prune: this one is triggered from the logs page,
    # which re-reads immediately afterwards. Without it the deleted
    # entries are still visible for up to a refresh interval and the
    # clear button looks like it did nothing
    response, _ = ElasticWrap(
        f"{INDEX_NAME}/_delete_by_query?refresh=true"
    ).post({"query": query})

    return response.get("deleted", 0)
