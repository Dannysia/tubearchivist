"""test channel aggregation building and parsing"""

# pylint: disable=protected-access

from channel.src.aggs import ChannelAggs


def test_query_has_downscale_agg():
    """downscale totals are filtered on new_height, like the video list"""
    aggs = ChannelAggs("UC1").build_query()["aggs"]
    assert aggs["downscale"]["filter"] == {
        "exists": {"field": "downscale.new_height"}
    }
    assert aggs["downscale"]["aggs"] == {
        "original_size": {"sum": {"field": "downscale.original_size"}},
        "new_size": {"sum": {"field": "downscale.new_size"}},
    }


def test_parse_downscale():
    """parse the downscale filter bucket"""
    agg = {
        "doc_count": 3,
        "original_size": {"value": 3000.0},
        "new_size": {"value": 1200.0},
    }
    assert ChannelAggs._parse_downscale(agg) == {
        "doc_count": 3,
        "original_size": 3000,
        "new_size": 1200,
        "saved": 1800,
    }


def test_parse_downscale_nothing_downscaled():
    """zeroed bucket, no videos matched the filter"""
    agg = {
        "doc_count": 0,
        "original_size": {"value": 0},
        "new_size": {"value": 0},
    }
    assert ChannelAggs._parse_downscale(agg) == ChannelAggs._empty_downscale()


def test_parse_downscale_grown():
    """an encode that came out bigger reports negative savings"""
    agg = {
        "doc_count": 1,
        "original_size": {"value": 1000.0},
        "new_size": {"value": 1500.0},
    }
    assert ChannelAggs._parse_downscale(agg)["saved"] == -500


def test_empty_response_has_downscale():
    """a channel without videos still serializes"""
    assert ChannelAggs("UC1")._empty()["downscale"] == {
        "doc_count": 0,
        "original_size": 0,
        "new_size": 0,
        "saved": 0,
    }
