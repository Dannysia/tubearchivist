"""test the queue write checks"""

import pytest
from common.src import queue_interact
from common.src.queue_interact import (
    BaseQueueInteract,
    IndexWriteError,
    QueueDocMissing,
)


class FakeWrap:
    answer: tuple = ({"result": "updated"}, 200)
    calls: list = []

    def __init__(self, path):
        self.path = path

    def post(self, data=False, ndjson=False):
        FakeWrap.calls.append(("post", self.path, data))
        return FakeWrap.answer

    def delete(self, data=False, refresh=False, print_error=True):
        FakeWrap.calls.append(("delete", self.path, data))
        return FakeWrap.answer


@pytest.fixture(autouse=True)
def fake_wrap(monkeypatch):
    FakeWrap.calls = []
    FakeWrap.answer = ({"result": "updated"}, 200)
    monkeypatch.setattr(queue_interact, "ElasticWrap", FakeWrap)

    return FakeWrap


class Queue(BaseQueueInteract):
    INDEX_NAME = "ta_test"


def test_update_posts_a_partial_doc(fake_wrap):
    Queue("doc1").update(status="finished")

    assert fake_wrap.calls == [
        (
            "post",
            "ta_test/_update/doc1?refresh=true",
            {"doc": {"status": "finished"}},
        )
    ]


def test_update_raises_when_es_rejects_it(fake_wrap):
    fake_wrap.answer = ({"error": "circuit_breaking_exception"}, 429)

    with pytest.raises(IndexWriteError) as err:
        Queue("doc1").update(status="finished")

    message = str(err.value)
    assert "ta_test" in message
    assert "doc1" in message
    assert "429" in message


def test_update_on_a_missing_doc_is_told_apart(fake_wrap):
    fake_wrap.answer = ({"error": "document_missing_exception"}, 404)

    with pytest.raises(QueueDocMissing):
        Queue("doc1").update(status="finished")


def test_a_missing_doc_is_still_a_write_error(fake_wrap):
    fake_wrap.answer = ({"error": "document_missing_exception"}, 404)

    with pytest.raises(IndexWriteError):
        Queue("doc1").update(status="finished")


def test_delete_item_accepts_404(fake_wrap):
    fake_wrap.answer = ({"result": "not_found"}, 404)

    Queue("doc1").delete_item()


def test_delete_item_raises_on_anything_else(fake_wrap):
    fake_wrap.answer = ({"error": "unavailable_shards_exception"}, 503)

    with pytest.raises(IndexWriteError):
        Queue("doc1").delete_item()


def test_update_by_query_raises_on_failures_inside_a_200(fake_wrap):
    fake_wrap.answer = ({"updated": 3, "failures": [{"id": "doc9"}]}, 200)

    with pytest.raises(IndexWriteError) as err:
        Queue()._update_by_query([], [], "ctx._source.status = 'queued';")

    assert "1 documents unwritten" in str(err.value)


def test_update_by_query_passes_on_a_clean_200(fake_wrap):
    fake_wrap.answer = ({"updated": 3, "failures": []}, 200)

    Queue()._update_by_query([], [], "ctx._source.status = 'queued';")


def test_delete_by_query_raises_on_failures_inside_a_200(fake_wrap):
    fake_wrap.answer = ({"deleted": 1, "failures": [{"id": "doc9"}]}, 200)

    with pytest.raises(IndexWriteError):
        Queue()._delete_by_query([])


def test_get_item_is_not_checked(monkeypatch):
    class ReadWrap(FakeWrap):
        def get(self, data=False, timeout=10, print_error=True):
            return {}, 404

    monkeypatch.setattr(queue_interact, "ElasticWrap", ReadWrap)

    source, status_code = Queue("doc1").get_item()

    assert source is None
    assert status_code == 404
