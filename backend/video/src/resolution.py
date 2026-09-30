from common.src.helper import get_duration_str
from downscale.src.constants import DOWNSCALE_LADDER

# streams is an object field, not nested: one height per video stream
HEIGHT_FIELD = "streams.height"

# below the last rung of the ladder, ie 144p and the like
BELOW_KEY = "below"
# no height indexed
UNKNOWN_KEY = "unknown"

RESOLUTION_KEYS = [str(i) for i in DOWNSCALE_LADDER] + [
    BELOW_KEY,
    UNKNOWN_KEY,
]

_SUB_AGGS = {
    "media_size": {"sum": {"field": "media_size"}},
    "duration": {"sum": {"field": "player.duration"}},
}


def _at_least(height: int) -> dict:
    return {"range": {HEIGHT_FIELD: {"gte": height}}}


def _has_height() -> dict:
    return {"exists": {"field": HEIGHT_FIELD}}


def resolution_filters() -> dict:
    filters: dict[str, dict] = {}
    for position, height in enumerate(DOWNSCALE_LADDER):
        clause = {"filter": [_at_least(height)]}
        if position:
            clause["must_not"] = [_at_least(DOWNSCALE_LADDER[position - 1])]

        filters[str(height)] = {"bool": clause}

    filters[BELOW_KEY] = {
        "bool": {
            "filter": [_has_height()],
            "must_not": [_at_least(DOWNSCALE_LADDER[-1])],
        }
    }
    filters[UNKNOWN_KEY] = {"bool": {"must_not": [_has_height()]}}

    return filters


def resolution_agg() -> dict:
    return {"filters": {"filters": resolution_filters()}, "aggs": _SUB_AGGS}


def _build_tier(key: str, bucket: dict) -> dict:
    duration = int(bucket["duration"]["value"])

    return {
        "key": key,
        "doc_count": bucket["doc_count"],
        "media_size": int(bucket["media_size"]["value"]),
        "duration": duration,
        "duration_str": get_duration_str(duration),
    }


def parse_resolution(agg: dict) -> list[dict]:
    buckets = agg["buckets"]

    return [_build_tier(key, buckets[key]) for key in RESOLUTION_KEYS]
