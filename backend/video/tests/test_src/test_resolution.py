"""test the resolution breakdown aggregation"""

from downscale.src.constants import DOWNSCALE_LADDER
from video.src.resolution import (
    BELOW_KEY,
    HEIGHT_FIELD,
    RESOLUTION_KEYS,
    UNKNOWN_KEY,
    empty_resolution,
    parse_resolution,
    resolution_agg,
    resolution_filters,
)


def test_tiers_are_the_downscale_ladder():
    """the categories are the heights a downscale can target"""
    ladder_keys = [str(i) for i in DOWNSCALE_LADDER]
    assert RESOLUTION_KEYS == ladder_keys + [BELOW_KEY, UNKNOWN_KEY]


def test_top_tier_has_no_ceiling():
    """nothing is above 2160p, so that filter only has a floor"""
    top = resolution_filters()["2160"]
    assert top == {
        "bool": {"filter": [{"range": {HEIGHT_FIELD: {"gte": 2160}}}]}
    }


def test_tier_excludes_the_one_above_it():
    """
    a 1200p video is counted in the 1080p tier and nowhere else, and so
    is a file carrying both a 1080p and a 2160p stream - in 2160p only.
    A plain gte/lt window on a multi valued field delivers neither
    """
    tier = resolution_filters()["1080"]
    assert tier == {
        "bool": {
            "filter": [{"range": {HEIGHT_FIELD: {"gte": 1080}}}],
            "must_not": [{"range": {HEIGHT_FIELD: {"gte": 1440}}}],
        }
    }


def test_below_needs_a_height():
    """under the last rung, but still something ffprobe measured"""
    below = resolution_filters()[BELOW_KEY]
    assert below == {
        "bool": {
            "filter": [{"exists": {"field": HEIGHT_FIELD}}],
            "must_not": [{"range": {HEIGHT_FIELD: {"gte": 240}}}],
        }
    }


def test_unknown_is_a_missing_height():
    """videos indexed without stream metadata"""
    unknown = resolution_filters()[UNKNOWN_KEY]
    assert unknown == {
        "bool": {"must_not": [{"exists": {"field": HEIGHT_FIELD}}]}
    }


def test_agg_carries_the_size_and_duration_sub_aggs():
    """the three panels are one query: count, size and time per tier"""
    assert resolution_agg() == {
        "filters": {"filters": resolution_filters()},
        "aggs": {
            "media_size": {"sum": {"field": "media_size"}},
            "duration": {"sum": {"field": "player.duration"}},
        },
    }


def build_response(counts: dict) -> dict:
    """build a filters agg response from a key to doc_count mapping"""
    return {
        "buckets": {
            key: {
                "doc_count": counts.get(key, 0),
                "media_size": {"value": counts.get(key, 0) * 100.0},
                "duration": {"value": counts.get(key, 0) * 60.0},
            }
            for key in RESOLUTION_KEYS
        }
    }


def test_parse_orders_tallest_first():
    """the list renders top down, without the frontend sorting it"""
    parsed = parse_resolution(build_response({}))
    assert [i["key"] for i in parsed] == RESOLUTION_KEYS


def test_parse_bucket():
    """one tier as it reads on all three panels"""
    parsed = parse_resolution(build_response({"1080": 3}))
    tier = next(i for i in parsed if i["key"] == "1080")
    assert tier["doc_count"] == 3
    assert tier["media_size"] == 300
    assert tier["duration"] == 180
    assert tier["duration_str"] == "3m"


def test_panels_reconcile_with_each_other():
    """the same tier set carries all three, so the panels line up"""
    parsed = parse_resolution(build_response({"2160": 2, "720": 5}))
    populated = [i["key"] for i in parsed if i["doc_count"]]
    assert [i["key"] for i in parsed if i["media_size"]] == populated
    assert [i["key"] for i in parsed if i["duration"]] == populated


def test_tiers_reconcile_with_the_video_count():
    """every video lands in exactly one tier, unmeasured ones included"""
    counts = {"2160": 4, "1080": 9, BELOW_KEY: 1, UNKNOWN_KEY: 6}
    parsed = parse_resolution(build_response(counts))
    assert sum(i["doc_count"] for i in parsed) == sum(counts.values())


def test_empty_matches_the_parsed_shape():
    """a channel with no videos serializes like a parsed response"""
    parsed = parse_resolution(build_response({}))
    assert empty_resolution() == parsed
