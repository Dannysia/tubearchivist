"""test that a checked index write reports a write that did not apply"""

import pytest
import requests
from common.src import index_generic
from common.src.index_generic import IndexWriteError, YouTubeItem


class Item(YouTubeItem):
    index_name = "ta_video"

    def __init__(self, youtube_id):
        # pylint: disable=super-init-not-called
        self.youtube_id = youtube_id
        self.es_path = f"{self.index_name}/_doc/{youtube_id}"
        self.json_data = {"youtube_id": youtube_id}


class FakeWrap:
    raises: BaseException | None = None
    answer: tuple = ({"result": "updated"}, 200)

    def __init__(self, path):
        self.path = path

    def put(self, data=False, refresh=False):
        if FakeWrap.raises:
            raise FakeWrap.raises

        return FakeWrap.answer


@pytest.fixture(autouse=True)
def fake_wrap(monkeypatch):
    FakeWrap.raises = None
    FakeWrap.answer = ({"result": "updated"}, 200)
    monkeypatch.setattr(index_generic, "ElasticWrap", FakeWrap)

    return FakeWrap


def test_a_rejected_write_raises_when_checked(fake_wrap):
    fake_wrap.raises = ValueError("failed to add item to index")

    with pytest.raises(IndexWriteError) as err:
        Item("video1").upload_to_es(checked=True)

    assert "video1" in str(err.value)


def test_an_unreachable_es_raises_when_checked(fake_wrap):
    fake_wrap.raises = requests.ConnectionError("connection refused")

    with pytest.raises(IndexWriteError):
        Item("video1").upload_to_es(checked=True)


def test_a_redirect_raises_when_checked(fake_wrap):
    fake_wrap.answer = ({}, 301)

    with pytest.raises(IndexWriteError):
        Item("video1").upload_to_es(checked=True)


def test_a_clean_write_does_not_raise(fake_wrap):
    Item("video1").upload_to_es(checked=True)


@pytest.mark.parametrize("code", [200, 201])
def test_both_created_and_updated_pass(fake_wrap, code):
    fake_wrap.answer = ({"result": "x"}, code)

    Item("video1").upload_to_es(checked=True)


def test_unchecked_callers_see_the_original_error(fake_wrap):
    fake_wrap.raises = ValueError("failed to add item to index")

    with pytest.raises(ValueError) as err:
        Item("video1").upload_to_es()

    assert not isinstance(err.value, IndexWriteError)
