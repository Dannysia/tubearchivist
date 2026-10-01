import pytest
from downscale.src.constants import DOWNSCALE_LADDER
from video.src.resolution import (
    BELOW_KEY,
    HEIGHT_FIELD,
    RESOLUTION_KEYS,
    UNKNOWN_KEY,
    parse_resolution,
    resolution_agg,
    resolution_filters,
)


def test_tiers_are_the_downscale_ladder():
    ladder_keys = [str(i) for i in DOWNSCALE_LADDER]
    assert RESOLUTION_KEYS == ladder_keys + [BELOW_KEY, UNKNOWN_KEY]


def test_top_tier_has_no_ceiling():
    top = resolution_filters()["2160"]
    assert top == {
        "bool": {"filter": [{"range": {HEIGHT_FIELD: {"gte": 2160}}}]}
    }


def test_tier_excludes_the_one_above_it():
    tier = resolution_filters()["1080"]
    assert tier == {
        "bool": {
            "filter": [{"range": {HEIGHT_FIELD: {"gte": 1080}}}],
            "must_not": [{"range": {HEIGHT_FIELD: {"gte": 1440}}}],
        }
    }


def test_below_needs_a_height():
    below = resolution_filters()[BELOW_KEY]
    assert below == {
        "bool": {
            "filter": [{"exists": {"field": HEIGHT_FIELD}}],
            "must_not": [{"range": {HEIGHT_FIELD: {"gte": 240}}}],
        }
    }


def test_unknown_is_a_missing_height():
    unknown = resolution_filters()[UNKNOWN_KEY]
    assert unknown == {
        "bool": {"must_not": [{"exists": {"field": HEIGHT_FIELD}}]}
    }


def test_agg_carries_the_size_and_duration_sub_aggs():
    assert resolution_agg() == {
        "filters": {"filters": resolution_filters()},
        "aggs": {
            "media_size": {"sum": {"field": "media_size"}},
            "duration": {"sum": {"field": "player.duration"}},
        },
    }


def build_response(counts: dict) -> dict:
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
    parsed = parse_resolution(build_response({}))
    assert [i["key"] for i in parsed] == RESOLUTION_KEYS


def test_parse_bucket():
    parsed = parse_resolution(build_response({"1080": 3}))
    tier = next(i for i in parsed if i["key"] == "1080")
    assert tier["doc_count"] == 3
    assert tier["media_size"] == 300
    assert tier["duration"] == 180
    assert tier["duration_str"] == "3m"


def _matches(clause: dict, height: int | None) -> bool:
    if "exists" in clause:
        return height is not None

    if "range" in clause:
        floor = clause["range"][HEIGHT_FIELD]["gte"]
        return height is not None and height >= floor

    query = clause["bool"]
    return all(
        _matches(i, height) for i in query.get("filter", [])
    ) and not any(_matches(i, height) for i in query.get("must_not", []))


@pytest.mark.parametrize(
    "height, expected",
    [
        (4320, "2160"),
        (2160, "2160"),
        (2159, "1440"),
        (1440, "1440"),
        (1080, "1080"),
        (721, "720"),
        (240, "240"),
        (239, BELOW_KEY),
        (0, BELOW_KEY),
        (None, UNKNOWN_KEY),
    ],
)
def test_every_height_lands_in_exactly_one_tier(height, expected):
    tiers = [
        key
        for key, clause in resolution_filters().items()
        if _matches(clause, height)
    ]
    assert tiers == [expected]


def test_the_ladder_is_tallest_first():
    assert DOWNSCALE_LADDER == sorted(DOWNSCALE_LADDER, reverse=True)
