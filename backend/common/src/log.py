from datetime import datetime, timezone
from typing import Literal

from common.src.es_connect import ElasticWrap

INDEX_NAME = "ta_log"

SourceType = Literal["notification", "application"]
LevelType = Literal["info", "error"]

FALLBACK_RETENTION_DAYS = 7
DAY_SECONDS = 86400


def now_epoch() -> int:
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
    retention = days or FALLBACK_RETENTION_DAYS
    cutoff = now_epoch() - retention * DAY_SECONDS
    data = {
        # es reads a bare number on a date field as epoch millis
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

    response, _ = ElasticWrap(
        f"{INDEX_NAME}/_delete_by_query?refresh=true"
    ).post({"query": query})

    return response.get("deleted", 0)
