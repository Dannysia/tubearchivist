"""tests for downscale queue lookups used by startup auto-resume"""

from unittest.mock import patch

from downscale.src.queue_interact import DownscaleInteract


def _es_response(hits: list[dict]) -> dict:
    return {"hits": {"hits": hits}}


def test_get_interrupted_maps_hits_to_docs():
    """
    queued/running local docs come back with their id merged into the
    doc, paginated in batches of 1000 rather than a single capped query
    - a restart backlog past 1000 jobs must not be silently truncated
    """
    hits = [
        {"_id": "doc1", "_source": {"status": "queued", "youtube_id": "a"}},
        {"_id": "doc2", "_source": {"status": "running", "youtube_id": "b"}},
    ]
    with patch("downscale.src.queue_interact.IndexPaginate") as mock_paginate:
        mock_paginate.return_value.get_results.return_value = hits

        result = DownscaleInteract.get_interrupted()

    args, kwargs = mock_paginate.call_args
    assert args[0] == "ta_downscale"
    assert args[1]["query"] == {
        "bool": {
            "must": [
                {"terms": {"status": ["queued", "running"]}},
                {"term": {"worker": {"value": ""}}},
            ]
        }
    }
    assert kwargs == {"size": 1000, "keep_source": True}
    assert result == [
        {"id": "doc1", "status": "queued", "youtube_id": "a"},
        {"id": "doc2", "status": "running", "youtube_id": "b"},
    ]


def test_get_interrupted_empty():
    """no queued/running docs returns an empty list"""
    with patch("downscale.src.queue_interact.IndexPaginate") as mock_paginate:
        mock_paginate.return_value.get_results.return_value = []

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


def test_requeue_interrupted_uses_a_single_update_by_query():
    """
    regression test: resetting a large interrupted backlog on startup
    must be one ES call, not one per job - the script resets
    status/message/task_id in bulk for anything still queued/running.
    Remote-held jobs (worker != "") are excluded from the sweep.
    """
    with patch("common.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.post.return_value = ({}, 200)

        DownscaleInteract().requeue_interrupted()

    mock_wrap.assert_called_once_with(
        "ta_downscale/_update_by_query?refresh=true"
    )
    data = mock_wrap.return_value.post.call_args.args[0]
    assert data["query"] == {
        "bool": {
            "must": [
                {"terms": {"status": ["queued", "running"]}},
                {"term": {"worker": {"value": ""}}},
            ],
            "must_not": [],
        }
    }
    script_source = data["script"]["source"]
    assert "ctx._source.status = 'queued';" in script_source
    assert "ctx._source.message = null;" in script_source
    assert "ctx._source.task_id = '';" in script_source
    assert "ctx._source.updated = " in script_source


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


def test_count_running_excludes_remote_jobs():
    """
    downscale_max_concurrent protects the TA host's own CPU, so remote
    (worker != "") running jobs must not count against it
    """
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (
            {"hits": {"total": {"value": 3}}},
            200,
        )

        result = DownscaleInteract.count_running()

    data = mock_wrap.return_value.get.call_args.kwargs["data"]
    assert data["query"] == {
        "bool": {
            "must": [
                {"term": {"status": {"value": "running"}}},
                {"term": {"worker": {"value": ""}}},
            ]
        }
    }
    assert result == 3


def test_build_queued_doc_defaults_worker_fields_for_a_local_job():
    """
    a freshly queued job explicitly carries worker="" (not just an
    absent field) - the count_running/get_interrupted/requeue_interrupted
    local-vs-remote filters all rely on an exact term match against it
    """
    video_json_data = {
        "channel": {"channel_id": "UC123", "channel_name": "chan"},
        "title": "title",
        "vid_thumb_url": None,
        "media_url": "a/b.mp4",
        "media_size": 100,
    }

    doc = DownscaleInteract.build_queued_doc(
        "video1", video_json_data, current_height=1080, target_height=720
    )

    assert doc["worker"] == ""
    assert doc["last_heartbeat"] == 0
    assert doc["progress"] == 0.0
    assert doc["stop_requested"] is False
    assert doc["ffmpeg_args"] == ""


def test_create_keys_the_doc_id_off_youtube_id():
    """
    doc_id is derived from doc["youtube_id"], not randomly generated -
    see docs/downscale-dedup/README.md. Verified against the ElasticWrap
    path used, since there's no uuid call left to assert on.
    """
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.put.return_value = ({}, 200)

        doc_id = DownscaleInteract().create({"youtube_id": "video1"})

    assert doc_id == "video1"
    mock_wrap.assert_called_once_with("ta_downscale/_doc/video1")


def test_create_is_deterministic_across_repeated_calls_for_one_video():
    """
    two create() calls for the same video (e.g. a racing double
    submission, or a retry after a different target_height) write to the
    same doc path rather than generating a new id each time
    """
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.put.return_value = ({}, 200)

        first_id = DownscaleInteract().create(
            {"youtube_id": "video1", "target_height": 720}
        )
        second_id = DownscaleInteract().create(
            {"youtube_id": "video1", "target_height": 480}
        )

    assert first_id == second_id
    paths = [call.args[0] for call in mock_wrap.call_args_list]
    assert paths == ["ta_downscale/_doc/video1", "ta_downscale/_doc/video1"]


def test_get_stale_leases_queries_remote_jobs_past_the_threshold():
    """
    only remote (worker != "") running jobs with a heartbeat older than
    the threshold are stale leases - a job that never set worker (local)
    or is heartbeating on time is excluded
    """
    hits = [
        {
            "_id": "doc1",
            "_source": {
                "status": "running",
                "worker": "gaming-pc",
                "last_heartbeat": 10,
            },
        }
    ]
    with patch("downscale.src.queue_interact.ElasticWrap") as mock_wrap:
        mock_wrap.return_value.get.return_value = (_es_response(hits), 200)

        result = DownscaleInteract.get_stale_leases(100)

    data = mock_wrap.return_value.get.call_args.kwargs["data"]
    assert data["query"] == {
        "bool": {
            "must": [
                {"term": {"status": {"value": "running"}}},
                {"range": {"last_heartbeat": {"lt": 100}}},
            ],
            "must_not": [{"term": {"worker": {"value": ""}}}],
        }
    }
    assert result == [
        {
            "id": "doc1",
            "status": "running",
            "worker": "gaming-pc",
            "last_heartbeat": 10,
        }
    ]
