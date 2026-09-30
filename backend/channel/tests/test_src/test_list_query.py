# pylint: disable=protected-access

import pytest
from channel.src.aggs import ChannelListAggs
from channel.src.constants import ChannelSortEnum
from channel.src.list_query import ChannelListQuery


@pytest.fixture
def stats():
    return {
        "UC1": {
            "doc_count": 10,
            "media_size": 500,
            "duration": 100,
            "duration_str": "1m 40s",
            "watch_progress": 0.5,
            "last_download": "2026-08-24T21:26:44.000Z",
            "last_published": "2026-08-01T00:00:00.000Z",
        },
        "UC2": {
            "doc_count": 3,
            "media_size": 900,
            "duration": 50,
            "duration_str": "50s",
            "watch_progress": 0.0,
            "last_download": "2026-01-01T00:00:00.000Z",
            "last_published": "2025-01-01T00:00:00.000Z",
        },
        "UC3": {
            "doc_count": 3,
            "media_size": 100,
            "duration": 20,
            "duration_str": "20s",
            "watch_progress": 1.0,
            "last_download": "2026-05-05T00:00:00.000Z",
            "last_published": "2026-05-05T00:00:00.000Z",
        },
    }


def build_query(sort_by, order="desc", query_filter=None):
    return ChannelListQuery(
        query_filter=query_filter,
        sort_by=ChannelSortEnum.from_name(sort_by),
        order=order,
    )


def sorted_ids(sort_by, order, stats, ids=None):
    query = build_query(sort_by, order)
    all_ids = list(ids or ["UC1", "UC2", "UC3", "UC4"])
    all_ids.sort(key=query._build_sort_key(stats), reverse=order == "desc")

    return all_ids


def test_sort_by_videos_desc(stats):
    assert sorted_ids("videos", "desc", stats) == ["UC1", "UC2", "UC3", "UC4"]


def test_sort_by_videos_asc(stats):
    assert sorted_ids("videos", "asc", stats) == ["UC4", "UC2", "UC3", "UC1"]


def test_sort_by_media_size(stats):
    assert sorted_ids("media_size", "desc", stats) == [
        "UC2",
        "UC1",
        "UC3",
        "UC4",
    ]


def test_sort_by_duration(stats):
    assert sorted_ids("duration", "desc", stats) == [
        "UC1",
        "UC2",
        "UC3",
        "UC4",
    ]


def test_sort_by_watch_progress(stats):
    assert sorted_ids("watch_progress", "desc", stats) == [
        "UC3",
        "UC1",
        "UC2",
        "UC4",
    ]


def test_sort_by_last_download(stats):
    assert sorted_ids("last_download", "desc", stats) == [
        "UC1",
        "UC3",
        "UC2",
        "UC4",
    ]


def test_sort_by_last_published_asc(stats):
    assert sorted_ids("last_published", "asc", stats) == [
        "UC4",
        "UC2",
        "UC3",
        "UC1",
    ]


def test_sort_key_falls_back_to_empty_stats():
    query = build_query("videos")
    assert query._build_sort_key({})("UC1") == 0


def test_stat_sorts_are_not_doc_fields():
    assert ChannelSortEnum.VIDEOS.is_stat is True
    assert ChannelSortEnum.WATCH_PROGRESS.is_stat is True
    assert ChannelSortEnum.NAME.is_stat is False
    assert ChannelSortEnum.SUBSCRIBERS.is_stat is False
    assert ChannelSortEnum.LAST_REFRESH.is_stat is False


def test_sort_enum_unknown_name():
    with pytest.raises(ValueError):
        ChannelSortEnum.from_name("not_a_sort")


def test_every_stat_sort_has_a_stat_key():
    empty = ChannelListAggs.empty_stats()
    for sort in ChannelSortEnum:
        if sort.is_stat:
            assert sort.value in empty


def test_build_query_without_filter():
    assert build_query("name")._build_query(None) == {"bool": {"must": []}}


def test_build_query_subscribed():
    expected = {
        "bool": {"must": [{"term": {"channel_subscribed": {"value": True}}}]}
    }
    assert build_query("name")._build_query("subscribed") == expected


def test_build_query_unsubscribed():
    expected = {
        "bool": {"must": [{"term": {"channel_subscribed": {"value": False}}}]}
    }
    assert build_query("name")._build_query("unsubscribed") == expected


def test_agg_query_all_channels():
    query = ChannelListAggs().build_query()
    assert query["query"] == {"match_all": {}}
    terms = query["aggs"]["by_channel"]["terms"]
    assert terms["field"] == "channel.channel_id"
    assert terms["size"] == ChannelListAggs.MAX_CHANNELS


def test_agg_query_limited_to_ids():
    query = ChannelListAggs(["UC1", "UC2"]).build_query()
    assert query["query"] == {"terms": {"channel.channel_id": ["UC1", "UC2"]}}
    assert query["aggs"]["by_channel"]["terms"]["size"] == 2


def test_agg_build_stats():
    bucket = {
        "key": "UC1",
        "doc_count": 4,
        "media_size": {"value": 1024.0},
        "duration": {"value": 200.0},
        "watched_duration": {"duration": {"value": 50.0}},
        "last_download": {"value_as_string": "2026-08-24T21:26:44.000Z"},
        "last_published": {},
    }
    assert ChannelListAggs._build_stats(bucket) == {
        "doc_count": 4,
        "media_size": 1024,
        "duration": 200,
        "duration_str": "3m 20s",
        "watch_progress": 0.25,
        "last_download": "2026-08-24T21:26:44.000Z",
        "last_published": None,
    }


def test_agg_build_stats_without_duration():
    bucket = {
        "key": "UC1",
        "doc_count": 0,
        "media_size": {"value": 0},
        "duration": {"value": 0},
        "watched_duration": {"duration": {"value": 0}},
        "last_download": {},
        "last_published": {},
    }
    assert ChannelListAggs._build_stats(bucket)["watch_progress"] == 0
