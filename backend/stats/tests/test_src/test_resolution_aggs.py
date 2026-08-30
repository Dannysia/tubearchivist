"""test the archive wide resolution aggregation"""

from stats.src.aggs import Resolution
from video.src.resolution import (
    RESOLUTION_KEYS,
    empty_resolution,
    resolution_agg,
)


def test_query_matches_the_channel_panel():
    """the dashboard and the channel about tab count the same tiers"""
    assert Resolution.data["aggs"]["by_resolution"] == resolution_agg()


def test_query_is_unfiltered():
    """the dashboard reports on the whole archive"""
    assert "query" not in Resolution.data
    assert Resolution.data["size"] == 0


def test_process_returns_every_tier():
    """parsed straight into the list the endpoint serializes"""
    buckets = {
        key: {
            "doc_count": 0,
            "media_size": {"value": 0},
            "duration": {"value": 0},
        }
        for key in RESOLUTION_KEYS
    }
    agg = Resolution()
    agg.get = lambda: {"by_resolution": {"buckets": buckets}}

    assert agg.process() == empty_resolution()


def test_process_without_aggregations():
    """an es response with nothing to parse"""
    agg = Resolution()
    agg.get = lambda: None

    assert agg.process() is None
