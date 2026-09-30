# pylint: disable=protected-access

import pytest
from channel.src import aggs as channel_aggs
from channel.src.aggs import ChannelAggs
from common.src.search_errors import SearchUnavailable
from downscale.src.constants import (
    SAVED_BUCKET_EDGES,
    VIDEO_SIZE_FIELDS,
    saved_percent_agg,
    transition_agg,
)
from video.src.resolution import resolution_agg


def a_transition_agg(buckets=None, other=0):
    return {
        "buckets": buckets or [],
        "sum_other_doc_count": other,
    }


def a_saved_agg(**counts):
    buckets = [{"key": "larger", "doc_count": counts.get("larger", 0)}]
    buckets += [
        {"key": str(edge), "doc_count": counts.get(str(edge), 0)}
        for edge in SAVED_BUCKET_EDGES
    ]
    return {"buckets": buckets}


def no_bands(**overrides):
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
    aggs = ChannelAggs("UC1").build_query()["aggs"]
    assert aggs["downscale"]["filter"] == {
        "exists": {"field": "downscale.new_height"}
    }
    assert aggs["downscale"]["aggs"] == {
        "original_size": {"sum": {"field": "downscale.original_size"}},
        "new_size": {"sum": {"field": "downscale.new_size"}},
        "by_transition": transition_agg(),
        "by_saved": saved_percent_agg(VIDEO_SIZE_FIELDS),
    }


def test_parse_downscale():
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
    agg = {
        "doc_count": 0,
        "original_size": {"value": 0},
        "new_size": {"value": 0},
        "by_transition": a_transition_agg(),
        "by_saved": a_saved_agg(),
    }
    assert ChannelAggs._parse_downscale(agg) == {
        "doc_count": 0,
        "original_size": 0,
        "new_size": 0,
        "saved": 0,
        "by_transition": {"transitions": [], "other_count": 0},
        "by_saved": no_bands(),
    }


def test_parse_downscale_grown():
    agg = {
        "doc_count": 1,
        "original_size": {"value": 1000.0},
        "new_size": {"value": 1500.0},
        "by_transition": a_transition_agg(),
        "by_saved": a_saved_agg(larger=1),
    }
    parsed = ChannelAggs._parse_downscale(agg)

    assert parsed["saved"] == -500
    assert parsed["by_saved"] == no_bands(grew=1)


def test_query_has_resolution_agg():
    aggs = ChannelAggs("UC1").build_query()["aggs"]
    assert aggs["by_resolution"] == resolution_agg()


def test_a_failed_search_is_an_error_not_zeros(monkeypatch):
    class Wrap:
        def __init__(self, path):
            pass

        def get(self, data=None):
            return {"error": {"type": "index_closed_exception"}}, 400

    monkeypatch.setattr(channel_aggs, "ElasticWrap", Wrap)

    with pytest.raises(SearchUnavailable):
        ChannelAggs("UC1").process()
