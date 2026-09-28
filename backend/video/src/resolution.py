from common.src.helper import get_duration_str
from downscale.src.constants import DOWNSCALE_LADDER

# multi valued: streams is an object field, not nested, so a file with
# several video streams has several heights; audio streams have none
HEIGHT_FIELD = "streams.height"

# below the last rung of the ladder, ie 144p and the like
BELOW_KEY = "below"
# no height indexed: predates stream metadata, or ffprobe failed on the
# file. Counted rather than dropped so the tiers add up to the video count
UNKNOWN_KEY = "unknown"

RESOLUTION_KEYS = [str(i) for i in DOWNSCALE_LADDER] + [
    BELOW_KEY,
    UNKNOWN_KEY,
]

# a video is in exactly one tier, so these sum over whole videos
_SUB_AGGS = {
    "media_size": {"sum": {"field": "media_size"}},
    "duration": {"sum": {"field": "player.duration"}},
}


def _at_least(height: int) -> dict:
    return {"range": {HEIGHT_FIELD: {"gte": height}}}


def _has_height() -> dict:
    return {"exists": {"field": HEIGHT_FIELD}}


def resolution_filters() -> dict:
    """
    one mutually exclusive filter per rung: a tier is "reaches this
    height and not the one above", so a 1200p video is counted once, in
    the 1080p tier. On a multi valued field that also means the tallest
    stream decides the tier - a gte/lt window would put a video with a
    1080p and a 2160p stream in both.
    """
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
    """ordered, tallest tier first"""
    buckets = agg["buckets"]

    return [_build_tier(key, buckets[key]) for key in RESOLUTION_KEYS]


def empty_resolution() -> list[dict]:
    zeroed = {
        "doc_count": 0,
        "media_size": {"value": 0},
        "duration": {"value": 0},
    }

    return [_build_tier(key, zeroed) for key in RESOLUTION_KEYS]
