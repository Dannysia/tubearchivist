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
