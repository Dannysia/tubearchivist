import re

from downscale.views import (
    _STATUS_SORT,
    _build_aggs_query,
    _build_must_list,
)


def test_no_filters_gives_empty_must_list():
    assert _build_must_list({}) == []


def test_status_filter():
    assert _build_must_list({"status": "failed"}) == [
        {"term": {"status": {"value": "failed"}}}
    ]


def test_channel_filter():
    assert _build_must_list({"channel": "UC123"}) == [
        {"term": {"channel_id": {"value": "UC123"}}}
    ]


def test_search_filter():
    assert _build_must_list({"q": "trailer"}) == [
        {"match_phrase_prefix": {"title": "trailer"}}
    ]


def test_encoder_filter():
    assert _build_must_list({"encoder": "av1_nvenc"}) == [
        {"term": {"encoder": {"value": "av1_nvenc"}}}
    ]


def test_size_change_smaller_uses_less_than():
    """new_size stays 0 until a job finishes, so 0 must not count"""
    [clause] = _build_must_list({"size_change": "smaller"})
    source = clause["script"]["script"]["source"]

    assert "doc['new_size'].value > 0" in source
    assert "doc['new_size'].value < doc['original_size'].value" in source
    assert "doc['new_size'].value > doc['original_size'].value" not in source


def test_size_change_larger_uses_greater_than():
    [clause] = _build_must_list({"size_change": "larger"})
    source = clause["script"]["script"]["source"]

    assert "doc['new_size'].value > 0" in source
    assert "doc['new_size'].value > doc['original_size'].value" in source
    assert "doc['new_size'].value < doc['original_size'].value" not in source


def test_all_filters_combine_with_and_semantics():
    must_list = _build_must_list(
        {
            "status": "pending_review",
            "channel": "UC123",
            "q": "trailer",
            "size_change": "smaller",
            "encoder": "av1_nvenc",
        }
    )

    assert len(must_list) == 5
    assert {"term": {"status": {"value": "pending_review"}}} in must_list
    assert {"term": {"channel_id": {"value": "UC123"}}} in must_list
    assert {"match_phrase_prefix": {"title": "trailer"}} in must_list
    assert {"term": {"encoder": {"value": "av1_nvenc"}}} in must_list
    assert any("script" in clause for clause in must_list)


def test_build_aggs_query_defaults_to_channel_multi_terms():
    agg_key, agg_body = _build_aggs_query("channel")

    assert agg_key == "channel_downscale"
    assert agg_body["multi_terms"]["terms"] == [
        {"field": "channel_name.keyword"},
        {"field": "channel_id"},
    ]


def test_build_aggs_query_encoder_uses_a_plain_terms_agg():
    """the encoder string is both the display and the filter value"""
    agg_key, agg_body = _build_aggs_query("encoder")

    assert agg_key == "encoder_downscale"
    assert agg_body == {"terms": {"field": "encoder", "size": 30}}


def test_status_sort_ranks_running_pending_review_failed_then_queued():
    script_clause, timestamp_clause = _STATUS_SORT
    source = script_clause["_script"]["script"]["source"]

    ranks = dict(re.findall(r"s == '(\w+)'\) return (\d+)", source))
    ranks = {status: int(rank) for status, rank in ranks.items()}

    assert ranks["running"] < ranks["pending_review"]
    assert ranks["pending_review"] < ranks["failed"]
    assert ranks["failed"] < ranks["queued"]
    assert "else return 4" in source
    assert script_clause["_script"]["order"] == "asc"
    assert timestamp_clause == {"timestamp": {"order": "desc"}}
