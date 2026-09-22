"""test channel aggregation building and parsing"""

# pylint: disable=protected-access

from channel.src.aggs import ChannelAggs
from downscale.src.constants import (
    SAVED_BUCKET_EDGES,
    VIDEO_SIZE_FIELDS,
    saved_percent_agg,
    transition_agg,
)
from video.src.resolution import empty_resolution, resolution_agg


def a_transition_agg(buckets=None, other=0):
    """a multi_terms response as ES returns one"""
    return {
        "buckets": buckets or [],
        "sum_other_doc_count": other,
    }


def a_saved_agg(**counts):
    """a savings band range response as ES returns one"""
    buckets = [{"key": "larger", "doc_count": counts.get("larger", 0)}]
    buckets += [
        {"key": str(edge), "doc_count": counts.get(str(edge), 0)}
        for edge in SAVED_BUCKET_EDGES
    ]
    return {"buckets": buckets}


def no_bands(**overrides):
    """the all-zero band payload, biggest band first"""
    payload = {
        "bands": [
            {"from": edge, "to": upper, "doc_count": 0}
            for edge, upper in [
                (50, None),
                (30, 50),
                (20, 30),
                (10, 20),
                (5, 10),
                (0, 5),
            ]
        ],
        "grew": 0,
        "unknown": 0,
    }
    payload.update(overrides)
    return payload


def test_query_has_downscale_agg():
    """downscale totals are filtered on new_height, like the video list"""
    aggs = ChannelAggs("UC1").build_query()["aggs"]
    assert aggs["downscale"]["filter"] == {
        "exists": {"field": "downscale.new_height"}
    }
    assert aggs["downscale"]["aggs"] == {
        "original_size": {"sum": {"field": "downscale.original_size"}},
        "new_size": {"sum": {"field": "downscale.new_size"}},
        "by_transition": transition_agg(),
        # the same bands the dashboard and the queue filter use, over
        # the video doc's own size fields
        "by_saved": saved_percent_agg(VIDEO_SIZE_FIELDS),
    }


def test_parse_downscale():
    """parse the downscale filter bucket"""
    agg = {
        "doc_count": 3,
        "original_size": {"value": 3000.0},
        "new_size": {"value": 1200.0},
        "by_transition": a_transition_agg(
            [
                {"key": [2160, 1080], "doc_count": 2},
                {"key": [1440, 1080], "doc_count": 1},
            ]
        ),
        "by_saved": a_saved_agg(**{"50": 2, "10": 1}),
    }
    assert ChannelAggs._parse_downscale(agg) == {
        "doc_count": 3,
        "original_size": 3000,
        "new_size": 1200,
        "saved": 1800,
        "by_transition": {
            "transitions": [
                {
                    "original_height": 2160,
                    "new_height": 1080,
                    "doc_count": 2,
                },
                {
                    "original_height": 1440,
                    "new_height": 1080,
                    "doc_count": 1,
                },
            ],
            "other_count": 0,
        },
        "by_saved": no_bands(
            bands=[
                {"from": 50, "to": None, "doc_count": 2},
                {"from": 30, "to": 50, "doc_count": 0},
                {"from": 20, "to": 30, "doc_count": 0},
                {"from": 10, "to": 20, "doc_count": 1},
                {"from": 5, "to": 10, "doc_count": 0},
                {"from": 0, "to": 5, "doc_count": 0},
            ]
        ),
    }


def test_parse_downscale_nothing_downscaled():
    """zeroed bucket, no videos matched the filter"""
    agg = {
        "doc_count": 0,
        "original_size": {"value": 0},
        "new_size": {"value": 0},
        "by_transition": a_transition_agg(),
        "by_saved": a_saved_agg(),
    }
    assert ChannelAggs._parse_downscale(agg) == ChannelAggs._empty_downscale()


def test_parse_downscale_grown():
    """an encode that came out bigger reports negative savings"""
    agg = {
        "doc_count": 1,
        "original_size": {"value": 1000.0},
        "new_size": {"value": 1500.0},
        "by_transition": a_transition_agg(),
        "by_saved": a_saved_agg(larger=1),
    }
    parsed = ChannelAggs._parse_downscale(agg)

    assert parsed["saved"] == -500
    # and the band payload says so too, in its own row rather than
    # folded into the smallest saving band
    assert parsed["by_saved"] == no_bands(grew=1)


def test_empty_response_has_downscale():
    """a channel without videos still serializes"""
    assert ChannelAggs("UC1")._empty()["downscale"] == {
        "doc_count": 0,
        "original_size": 0,
        "new_size": 0,
        "saved": 0,
        "by_transition": {"transitions": [], "other_count": 0},
        "by_saved": no_bands(),
    }


def test_query_has_resolution_agg():
    """the about panel breaks the channel down by the downscale ladder"""
    aggs = ChannelAggs("UC1").build_query()["aggs"]
    assert aggs["by_resolution"] == resolution_agg()


def test_empty_response_has_resolution():
    """a channel without videos still serializes"""
    assert ChannelAggs("UC1")._empty()["by_resolution"] == empty_resolution()
