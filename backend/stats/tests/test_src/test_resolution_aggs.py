import pytest
from common.src.search_errors import SearchUnavailable
from stats.src import aggs
from stats.src.aggs import Resolution
from video.src.resolution import RESOLUTION_KEYS, resolution_agg


def test_query_matches_the_channel_panel():
    assert Resolution.data["aggs"]["by_resolution"] == resolution_agg()


def test_query_is_unfiltered():
    assert "query" not in Resolution.data
    assert Resolution.data["size"] == 0


def test_process_returns_every_tier():
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

    tiers = agg.process()
    assert [i["key"] for i in tiers] == list(RESOLUTION_KEYS)
    assert all(i["doc_count"] == 0 for i in tiers)


def test_a_failed_search_is_an_error_not_zeros(monkeypatch):
    class Wrap:
        def __init__(self, path):
            pass

        def get(self, data=None):
            return {"error": {"type": "index_closed_exception"}}, 400

    monkeypatch.setattr(aggs, "ElasticWrap", Wrap)

    with pytest.raises(SearchUnavailable):
        Resolution().process()
