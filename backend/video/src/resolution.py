"""resolution breakdown aggregation, shared by the stats endpoints"""

from common.src.helper import get_duration_str
from downscale.src.constants import DOWNSCALE_LADDER

# The height of the video streams of a document. streams is an object
# field, not nested, so this is multi valued for a file that carries more
# than one video stream, and only video streams have a height at all -
# MediaStreamExtractor never writes one for audio.
HEIGHT_FIELD = "streams.height"

# below the last rung of the ladder, ie 144p and the like
BELOW_KEY = "below"
# no height indexed: extraction predates stream metadata, or ffprobe
# failed on the file. Counted rather than dropped so the tiers plus
# these two always add back up to the video count
UNKNOWN_KEY = "unknown"

RESOLUTION_KEYS = [str(i) for i in DOWNSCALE_LADDER] + [
    BELOW_KEY,
    UNKNOWN_KEY,
]

# a video is in exactly one tier, so these sum over whole videos and the
# three panels each add up to the archive total
_SUB_AGGS = {
    "media_size": {"sum": {"field": "media_size"}},
    "duration": {"sum": {"field": "player.duration"}},
}


def _at_least(height: int) -> dict:
    """es clause matching a video with a stream at or above height"""
    return {"range": {HEIGHT_FIELD: {"gte": height}}}


def _has_height() -> dict:
    """es clause matching a video with any indexed stream height"""
    return {"exists": {"field": HEIGHT_FIELD}}


def resolution_filters() -> dict:
    """
    build one mutually exclusive filter per rung of the ladder. A tier
    is "reaches this height and not the one above it", so anything
    between two rungs falls to the lower one - a 1200p video is counted
    once, in the 1080p tier, and never gets an entry of its own.

    On a multi valued field that also means the tallest stream decides
    the tier. Filtering on a plain gte/lt window instead would put a
    video carrying a 1080p and a 2160p stream in both tiers, and the
    counts would stop adding up
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
    """
    the whole aggregation, sub aggs included, so both callers report the
    same numbers and parse_resolution can rely on the shape
    """
    return {"filters": {"filters": resolution_filters()}, "aggs": _SUB_AGGS}


def _build_tier(key: str, bucket: dict) -> dict:
    """one tier, on all three panels: count, size and time"""
    duration = int(bucket["duration"]["value"])

    return {
        "key": key,
        "doc_count": bucket["doc_count"],
        "media_size": int(bucket["media_size"]["value"]),
        "duration": duration,
        "duration_str": get_duration_str(duration),
    }


def parse_resolution(agg: dict) -> list[dict]:
    """parse the filters agg into an ordered list, tallest tier first"""
    buckets = agg["buckets"]

    return [_build_tier(key, buckets[key]) for key in RESOLUTION_KEYS]


def empty_resolution() -> list[dict]:
    """zeroed tiers, for a scope with no videos to aggregate"""
    zeroed = {
        "doc_count": 0,
        "media_size": {"value": 0},
        "duration": {"value": 0},
    }

    return [_build_tier(key, zeroed) for key in RESOLUTION_KEYS]
