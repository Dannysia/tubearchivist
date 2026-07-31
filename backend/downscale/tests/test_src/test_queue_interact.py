"""tests for downscale queue lookups used by startup auto-resume"""

from unittest.mock import patch

from downscale.src.queue_interact import DownscaleInteract


def _es_response(hits: list[dict]) -> dict:
    return {"hits": {"hits": hits}}


def test_get_interrupted_maps_hits_to_docs():
    """queued/running docs come back with their id merged into the doc"""
    hits = [
        {"_id": "doc1", "_source": {"status": "queued", "youtube_id": "a"}},
        {"_id": "doc2", "_source": {"status": "running", "youtube_id": "b"}},
    ]
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response(hits), 200)

        result = DownscaleInteract.get_interrupted()

    query = mock_wrap.return_value.get.call_args.kwargs["data"]["query"]
    assert query == {"terms": {"status": ["queued", "running"]}}
    assert result == [
        {"id": "doc1", "status": "queued", "youtube_id": "a"},
        {"id": "doc2", "status": "running", "youtube_id": "b"},
    ]


def test_get_interrupted_empty():
    """no queued/running docs returns an empty list"""
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response([]), 200)

        result = DownscaleInteract.get_interrupted()

    assert result == []


def test_get_next_queued_maps_hits_and_sorts_oldest_first():
    """oldest queued job first, id merged into the doc"""
    hits = [
        {"_id": "doc1", "_source": {"status": "queued", "timestamp": 1}},
        {"_id": "doc2", "_source": {"status": "queued", "timestamp": 2}},
    ]
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response(hits), 200)

        result = DownscaleInteract.get_next_queued(5)

    data = mock_wrap.return_value.get.call_args.kwargs["data"]
    assert data["query"] == {
        "bool": {
            "must": [
                {"term": {"status": {"value": "queued"}}},
                {"term": {"task_id": {"value": ""}}},
            ]
        }
    }
    assert data["sort"] == [{"timestamp": {"order": "asc"}}]
    assert data["size"] == 5
    assert result == [
        {"id": "doc1", "status": "queued", "timestamp": 1},
        {"id": "doc2", "status": "queued", "timestamp": 2},
    ]


def test_get_next_queued_excludes_already_dispatched_jobs():
    """
    regression test: a job stays status=queued from the moment it's
    dispatched until its task actually reaches _reserve_slot() and
    flips it to running, so status=queued alone can't tell "never
    dispatched" apart from "just dispatched, task hasn't started yet".
    Without also filtering on an empty task_id, two
    dispatch_pending_downscales() calls close together could both pick
    the same job and start two celery tasks for one doc.
    """
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response([]), 200)

        DownscaleInteract.get_next_queued(5)

    data = mock_wrap.return_value.get.call_args.kwargs["data"]
    assert {"term": {"task_id": {"value": ""}}} in data["query"]["bool"][
        "must"
    ]


def test_get_next_queued_unlimited_uses_a_capped_size():
    """limit=None (unlimited concurrency) still caps the query size"""
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response([]), 200)

        DownscaleInteract.get_next_queued(None)

    data = mock_wrap.return_value.get.call_args.kwargs["data"]
    assert data["size"] == 1000


def test_get_next_queued_zero_or_negative_limit_skips_the_query():
    """no free slots (limit<=0) shouldn't even hit ES"""
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        assert DownscaleInteract.get_next_queued(0) == []
        assert DownscaleInteract.get_next_queued(-1) == []

    mock_wrap.assert_not_called()


def test_get_all_tmp_filenames_returns_basenames():
    """tmp_file_path is reduced to its basename for cache-keep matching"""
    hits = [
        {"_source": {"tmp_file_path": "/cache/downscale/a_720p.mp4"}},
        {"_source": {"tmp_file_path": "/cache/downscale/b_480p.mp4"}},
    ]
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response(hits), 200)

        result = DownscaleInteract.get_all_tmp_filenames()

    assert result == {"a_720p.mp4", "b_480p.mp4"}


def test_get_all_tmp_filenames_skips_docs_without_tmp_path():
    """a doc with no tmp_file_path (e.g. never reserved a slot) is skipped"""
    hits = [{"_source": {}}]
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response(hits), 200)

        result = DownscaleInteract.get_all_tmp_filenames()

    assert result == set()
