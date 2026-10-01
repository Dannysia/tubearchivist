"""test that a failed put tells an unavailable es from a rejected doc"""

from types import SimpleNamespace

import pytest
from common.src import es_connect
from common.src.es_connect import ElasticUnavailable, ElasticWrap


def _answer(monkeypatch, status):
    response = SimpleNamespace(
        ok=status < 400,
        status_code=status,
        text="",
        json=lambda: {"result": "created"},
    )
    monkeypatch.setattr(
        es_connect.requests, "put", lambda url, **kwargs: response
    )


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_an_unavailable_es_raises_its_own_type(monkeypatch, status):
    _answer(monkeypatch, status)

    with pytest.raises(ElasticUnavailable):
        ElasticWrap("ta_video/_doc/x").put({"a": 1})


@pytest.mark.parametrize("status", [400, 404, 409])
def test_a_rejected_doc_stays_a_plain_value_error(monkeypatch, status):
    _answer(monkeypatch, status)

    with pytest.raises(ValueError) as err:
        ElasticWrap("ta_video/_doc/x").put({"a": 1})

    assert not isinstance(err.value, ElasticUnavailable)


def test_a_clean_write_returns_the_answer(monkeypatch):
    _answer(monkeypatch, 201)

    assert ElasticWrap("ta_video/_doc/x").put({"a": 1}) == (
        {"result": "created"},
        201,
    )
