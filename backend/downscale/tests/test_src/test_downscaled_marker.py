"""test that every downscaled lookup agrees on the same set of videos"""

from channel.src.aggs import ChannelAggs
from downscale.src.constants import DOWNSCALED_FIELD, downscaled_filter
from stats.src.aggs import Downscale
from video.src.query_building import QueryBuilder


def test_filter_shape():
    """the one clause everything else is built from"""
    assert downscaled_filter() == {"exists": {"field": DOWNSCALED_FIELD}}


def test_filter_is_not_shared_state():
    """each caller embeds it in its own query, so hand out a fresh dict"""
    first = downscaled_filter()
    first["exists"]["field"] = "mutated"

    assert downscaled_filter()["exists"]["field"] == DOWNSCALED_FIELD


def test_video_filter_uses_the_shared_marker():
    """the video list filter"""
    assert QueryBuilder.parse_downscale(True) == downscaled_filter()
    assert QueryBuilder.parse_downscale(False) == {
        "bool": {"must_not": downscaled_filter()}
    }


def test_channel_panel_uses_the_shared_marker():
    """the channel about page savings panel"""
    aggs = ChannelAggs("UC1").build_query()["aggs"]
    assert aggs["downscale"]["filter"] == downscaled_filter()


def test_dashboard_stats_use_the_shared_marker():
    """the dashboard savings section"""
    assert Downscale.data["query"] == downscaled_filter()


def test_every_surface_reports_on_the_same_set():
    """
    the video filter, the channel panel and the dashboard all answer
    "has this been downscaled" and must answer it identically - when
    these were three separate literals, one could drift and silently
    report on a different set of videos than the other two
    """
    surfaces = [
        QueryBuilder.parse_downscale(True),
        ChannelAggs("UC1").build_query()["aggs"]["downscale"]["filter"],
        Downscale.data["query"],
    ]

    assert all(i == surfaces[0] for i in surfaces)
