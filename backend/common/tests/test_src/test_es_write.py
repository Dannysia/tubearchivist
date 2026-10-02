"""test the shared check of what an es write answered"""

import json

import pytest
from common.src import es_connect
from common.src.es_connect import (
    IndexWriteError,
    bulk_write,
    check_write,
    rejected_ids,
    write_failure,
)

REJECTED = {
    "errors": True,
    "items": [
        {"index": {"_id": "a", "result": "created"}},
        {"update": {"_id": "b", "error": {"type": "mapper_parsing"}}},
    ],
}


@pytest.mark.parametrize("code", [200, 201])
def test_a_clean_answer_is_no_failure(code):
    assert write_failure({"errors": False}, code) is None


@pytest.mark.parametrize("code", [400, 404, 409, 503])
def test_a_failed_status_is_a_failure(code):
    assert str(code) in write_failure({"error": "x"}, code)


def test_item_errors_inside_a_200_are_a_failure():
    failure = write_failure(REJECTED, 200)

    assert "1 items" in failure
    assert "mapper_parsing" in failure


def test_by_query_failures_inside_a_200_are_a_failure():
    failure = write_failure({"failures": [{"id": "x"}, {"id": "y"}]}, 200)

    assert "2 documents unwritten" in failure


def test_check_write_raises_with_what_failed():
    with pytest.raises(IndexWriteError) as err:
        check_write(REJECTED, 200, "ta_download: adding")

    assert str(err.value).startswith("ta_download: adding failed")


def test_rejected_ids_names_only_the_items_that_failed():
    assert rejected_ids(REJECTED) == ["b"]


@pytest.mark.parametrize(
    "refresh, path", [(False, "_bulk"), (True, "_bulk?refresh=true")]
)
def test_bulk_write_sends_ndjson_with_a_trailing_newline(
    monkeypatch, refresh, path
):
    sent = {}

    class Wrap:
        def __init__(self, url_path):
            sent["path"] = url_path

        def post(self, data=False, ndjson=False):
            sent["data"], sent["ndjson"] = data, ndjson
            return {"errors": False}, 200

    monkeypatch.setattr(es_connect, "ElasticWrap", Wrap)

    bulk_write([({"index": {"_id": "a"}}, {"title": "t"})], refresh=refresh)

    assert sent["path"] == path
    assert sent["ndjson"] is True
    assert sent["data"].endswith("\n")
    lines = sent["data"].strip().split("\n")
    assert [json.loads(i) for i in lines] == [
        {"index": {"_id": "a"}},
        {"title": "t"},
    ]
