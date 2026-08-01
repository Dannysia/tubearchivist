"""
tests for the downscale list/bulk-by-filter query building.

_build_must_list lives in views.py rather than src/ (it's the query
translation for both GET listing and the bulk-by-filter action), but it's
a pure function with no request/ES dependency, so it's tested directly
here rather than via HTTP - this project's tests exercise src/-layer
logic, not the Django view/HTTP layer itself.
"""

import re

from downscale.views import _STATUS_SORT, _build_must_list


def test_no_filters_gives_empty_must_list():
    """an empty query matches everything - no bool clauses at all"""
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


def test_size_change_smaller_uses_less_than():
    """
    "smaller" must compare new_size < original_size, and must require
    new_size > 0 so queued/running/failed jobs (new_size still 0, never
    set until _finish_success) don't count as "smaller"
    """
    [clause] = _build_must_list({"size_change": "smaller"})
    source = clause["script"]["script"]["source"]

    assert "doc['new_size'].value > 0" in source
    assert "doc['new_size'].value < doc['original_size'].value" in source
    assert "doc['new_size'].value > doc['original_size'].value" not in source


def test_size_change_larger_uses_greater_than():
    """ "larger" is the mirror image - > instead of <, same > 0 guard"""
    [clause] = _build_must_list({"size_change": "larger"})
    source = clause["script"]["script"]["source"]

    assert "doc['new_size'].value > 0" in source
    assert "doc['new_size'].value > doc['original_size'].value" in source
    assert "doc['new_size'].value < doc['original_size'].value" not in source


def test_all_filters_combine_with_and_semantics():
    """
    every active filter must be a separate "must" clause (AND), not
    merged/overwritten - e.g. status=pending_review + channel=X should
    require both, not just whichever was built last
    """
    must_list = _build_must_list(
        {
            "status": "pending_review",
            "channel": "UC123",
            "q": "trailer",
            "size_change": "smaller",
        }
    )

    assert len(must_list) == 4
    assert {"term": {"status": {"value": "pending_review"}}} in must_list
    assert {"term": {"channel_id": {"value": "UC123"}}} in must_list
    assert {"match_phrase_prefix": {"title": "trailer"}} in must_list
    assert any("script" in clause for clause in must_list)


def test_status_sort_ranks_running_pending_review_failed_then_queued():
    """
    unfiltered list view: running < pending_review < failed < queued <
    everything else, timestamp desc is only the tiebreaker
    """
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
