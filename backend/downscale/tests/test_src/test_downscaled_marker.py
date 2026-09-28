"""test that every downscaled lookup agrees on the same set of videos"""

from channel.src.aggs import ChannelAggs
from downscale.src.constants import DOWNSCALED_FIELD, downscaled_filter
from stats.src.aggs import Downscale
from video.src.query_building import QueryBuilder


def test_filter_shape():
    assert downscaled_filter() == {"exists": {"field": DOWNSCALED_FIELD}}


def test_filter_is_not_shared_state():
    """each caller embeds it in its own query, so hand out a fresh dict"""
    first = downscaled_filter()
    first["exists"]["field"] = "mutated"

    assert downscaled_filter()["exists"]["field"] == DOWNSCALED_FIELD


def test_video_filter_uses_the_shared_marker():
    assert QueryBuilder.parse_downscale(True) == downscaled_filter()
    assert QueryBuilder.parse_downscale(False) == {
        "bool": {"must_not": downscaled_filter()}
    }


def test_channel_panel_uses_the_shared_marker():
    aggs = ChannelAggs("UC1").build_query()["aggs"]
    assert aggs["downscale"]["filter"] == downscaled_filter()


def test_dashboard_stats_use_the_shared_marker():
    assert Downscale.data["query"] == downscaled_filter()


def test_every_surface_reports_on_the_same_set():
    surfaces = [
        QueryBuilder.parse_downscale(True),
        ChannelAggs("UC1").build_query()["aggs"]["downscale"]["filter"],
        Downscale.data["query"],
    ]

    assert all(i == surfaces[0] for i in surfaces)
