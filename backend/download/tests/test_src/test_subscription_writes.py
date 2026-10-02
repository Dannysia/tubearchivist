"""test a subscription scan whose writes fail"""

import pytest
from common.src import es_connect
from common.src.es_connect import IndexWriteError
from download.src import extraction_queue
from download.src.extraction_queue import ExtractionQueue
from download.src.subscriptions import (
    _advance_next_check,
    _run_subscription_scan,
)

CONFIG = {"subscriptions": {"frequency_hours": 24, "jitter_percent": 0}}
ENTRY = {"type": "channel", "url": "UC1", "vid_type": None, "limit": None}
REJECTED = {"errors": True, "items": [{"index": {"error": {"type": "x"}}}]}


class FakeES:
    def __init__(self, answers):
        self.answers = answers
        self.posts = []

    def wrap(self):
        es = self

        class Wrap:
            def __init__(self, path):
                self.path = path

            def post(self, data=None, ndjson=False):
                es.posts.append(self.path)
                for prefix, answer in es.answers.items():
                    if self.path.startswith(prefix):
                        return answer

                return {"errors": False}, 200

        return Wrap


def _patch(monkeypatch, answers):
    es = FakeES(answers)
    monkeypatch.setattr(extraction_queue, "ElasticWrap", es.wrap())
    monkeypatch.setattr(es_connect, "ElasticWrap", es.wrap())
    return es


@pytest.mark.parametrize(
    "answer", [({"error": "unavailable"}, 503), (REJECTED, 200)]
)
def test_a_failed_enqueue_raises(monkeypatch, answer):
    _patch(monkeypatch, {"_bulk?refresh=true": answer})

    with pytest.raises(IndexWriteError):
        ExtractionQueue().add_to_queue([ENTRY])


def test_a_failed_enqueue_does_not_advance(monkeypatch):
    es = _patch(monkeypatch, {"_bulk?refresh=true": ({"error": "x"}, 503)})

    with pytest.raises(IndexWriteError):
        _run_subscription_scan(
            None,
            CONFIG,
            [{"channel_id": "UC1"}],
            "ta_channel",
            "channel_id",
            "channel_subscribed_next_check",
            lambda due: [ENTRY],
        )

    assert "_bulk" not in es.posts


@pytest.mark.parametrize(
    "answer", [({"error": "unavailable"}, 503), (REJECTED, 200)]
)
def test_a_failed_advance_raises(monkeypatch, answer):
    _patch(monkeypatch, {"_bulk": answer})

    with pytest.raises(IndexWriteError):
        _advance_next_check(
            "ta_channel",
            "channel_id",
            "channel_subscribed_next_check",
            [{"channel_id": "UC1"}],
            CONFIG,
        )
