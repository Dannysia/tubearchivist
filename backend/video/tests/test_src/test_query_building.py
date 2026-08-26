"""test video query building"""

import pytest
from video.src.query_building import QueryBuilder


def test_initialization():
    """init constructor"""
    qb = QueryBuilder(user_id=1)
    assert qb.user_id == 1
    assert not qb.request_params


def test_build_data():
    """test for correct key building"""
    qb = QueryBuilder(
        user_id=1,
        channel="test_channel",
        watch="watched",
        type="videos",
        sort="published",
        order="desc",
    )
    result = qb.build_data()
    assert "query" in result
    assert "sort" in result
    assert result["sort"] == [{"published": {"order": "desc"}}]


def test_parse_watch():
    """watched query building"""
    qb = QueryBuilder(user_id=1, watch="watched")
    result = qb.parse_watch("watched")
    assert result == {"match": {"player.watched": True}}

    result = qb.parse_watch("unwatched")
    assert result == {"match": {"player.watched": False}}

    with pytest.raises(ValueError):
        qb.parse_watch("invalid")


def test_parse_type():
    """test type is parsed"""
    qb = QueryBuilder(user_id=1, type="videos")
    with pytest.raises(ValueError):
        qb.parse_type("invalid")

    result = qb.parse_type("videos")
    assert result == {"match": {"vid_type": "videos"}}


def test_parse_sort():
    """test sort and order"""
    qb = QueryBuilder(user_id=1, sort="views", order="desc")
    result = qb.parse_sort()
    assert result == {"sort": [{"stats.view_count": {"order": "desc"}}]}

    with pytest.raises(ValueError):
        qb = QueryBuilder(user_id=1, sort="invalid")
        qb.parse_sort()

    with pytest.raises(ValueError):
        qb = QueryBuilder(user_id=1, sort="stats.view_count", order="invalid")
        qb.parse_sort()


def test_parse_downscale():
    """downscaled and not downscaled query building"""
    qb = QueryBuilder(user_id=1, downscale=True)
    exists = {"exists": {"field": "downscale.new_height"}}

    assert qb.parse_downscale(True) == exists
    assert qb.parse_downscale(False) == {"bool": {"must_not": exists}}


def test_parse_downscale_encoder():
    """encoder query building, any string the index holds"""
    qb = QueryBuilder(user_id=1, downscale_encoder="h265")
    assert qb.parse_downscale_encoder("h265") == {
        "term": {"downscale.encoder": {"value": "h265"}}
    }
    assert qb.parse_downscale_encoder("nvenc_av1") == {
        "term": {"downscale.encoder": {"value": "nvenc_av1"}}
    }


def test_build_query_downscale_false_is_not_skipped():
    """downscale=false filters, it is not the same as unset"""
    qb = QueryBuilder(user_id=1, downscale=False)
    must_list = qb.build_query()["bool"]["must"]
    assert must_list == [
        {"bool": {"must_not": {"exists": {"field": "downscale.new_height"}}}}
    ]


def test_build_query_without_downscale():
    """no downscale params, no downscale clauses"""
    qb = QueryBuilder(user_id=1, type="videos")
    assert qb.build_query()["bool"]["must"] == [
        {"match": {"vid_type": "videos"}}
    ]


def test_build_query_downscale_combined():
    """downscale filters stack with the other filters"""
    qb = QueryBuilder(
        user_id=1,
        channel="test_channel",
        downscale=True,
        downscale_encoder="h265_vaapi",
    )
    must_list = qb.build_query()["bool"]["must"]
    assert must_list == [
        {"match": {"channel.channel_id": "test_channel"}},
        {"exists": {"field": "downscale.new_height"}},
        {"term": {"downscale.encoder": {"value": "h265_vaapi"}}},
    ]
