from unittest import mock

import pytest
from common.src.history import (
    MISSING,
    HistoryQuery,
    HistoryTracker,
    decode_change,
    decode_value,
    encode_value,
    track_changes,
    track_deactivation,
)


@pytest.fixture(name="video_doc")
def fixture_video_doc():
    return {
        "youtube_id": "vid1",
        "active": True,
        "title": "Old Title",
        "description": "Old description",
        "category": ["Music"],
        "tags": ["b", "a"],
        "published": 1600000000,
        "vid_type": "videos",
        "vid_thumb_url": "https://i.ytimg.com/vi/vid1/max.jpg?sqp=one&rs=x",
        "stats": {
            "view_count": 100,
            "like_count": 10,
            "dislike_count": 1,
            "average_rating": 0,
        },
        "channel": {"channel_id": "chan1"},
    }


def _tracker(item_type="video", item_id="vid1"):
    return HistoryTracker(item_type, item_id, timestamp=1700000000)


def test_no_changes_returns_empty(video_doc):
    changes = _tracker().build_changes(video_doc, video_doc.copy())
    assert changes == []


def test_title_change(video_doc):
    new = video_doc.copy()
    new["title"] = "New Title"
    changes = _tracker().build_changes(video_doc, new)

    assert len(changes) == 1
    change = changes[0]
    assert change["field"] == "title"
    assert change["old_value"] == "Old Title"
    assert change["new_value"] == "New Title"
    assert change["old_value_type"] == "string"
    assert change["item_type"] == "video"
    assert change["item_id"] == "vid1"
    assert change["channel_id"] == "chan1"
    assert change["timestamp"] == 1700000000
    assert "old_num" not in change


def test_nested_stat_change(video_doc):
    new = video_doc.copy()
    new["stats"] = video_doc["stats"] | {"view_count": 150}
    changes = _tracker().build_changes(video_doc, new)

    assert len(changes) == 1
    change = changes[0]
    assert change["field"] == "stats.view_count"
    assert change["old_num"] == 100
    assert change["new_num"] == 150
    assert change["delta"] == 50
    assert change["old_value"] == "100"


def test_list_reorder_is_not_a_change(video_doc):
    new = video_doc.copy()
    new["tags"] = ["a", "b"]
    assert _tracker().build_changes(video_doc, new) == []


def test_list_content_change(video_doc):
    new = video_doc.copy()
    new["tags"] = ["a", "b", "c"]
    changes = _tracker().build_changes(video_doc, new)

    assert len(changes) == 1
    assert changes[0]["field"] == "tags"
    assert changes[0]["new_value_type"] == "json"
    assert decode_value(changes[0]["new_value"], "json") == ["a", "b", "c"]


def test_thumb_query_params_ignored(video_doc):
    new = video_doc.copy()
    new["vid_thumb_url"] = "https://i.ytimg.com/vi/vid1/max.jpg?sqp=two&rs=y"
    assert _tracker().build_changes(video_doc, new) == []


def test_thumb_path_change(video_doc):
    new = video_doc.copy()
    new["vid_thumb_url"] = "https://i.ytimg.com/vi/vid1/hq.jpg?sqp=two"
    changes = _tracker().build_changes(video_doc, new)

    assert len(changes) == 1
    assert changes[0]["field"] == "vid_thumb_url"


def test_removed_field(video_doc):
    new = video_doc.copy()
    del new["description"]
    changes = _tracker().build_changes(video_doc, new)

    assert len(changes) == 1
    assert changes[0]["field"] == "description"
    assert changes[0]["new_value"] is None
    assert changes[0]["new_value_type"] == "missing"
    assert decode_value(None, "missing") is MISSING


def test_multiple_changes_share_refresh_id(video_doc):
    new = video_doc.copy()
    new["title"] = "New Title"
    new["stats"] = video_doc["stats"] | {"view_count": 150}
    changes = _tracker().build_changes(video_doc, new)

    assert len(changes) == 2
    assert len({i["refresh_id"] for i in changes}) == 1


def test_doc_id_is_deterministic(video_doc):
    tracker = _tracker()
    # pylint: disable=protected-access
    assert tracker._build_doc_id("title") == "vid1-1700000000-title"


def test_unknown_item_type_raises(video_doc):
    with pytest.raises(ValueError):
        HistoryTracker("subtitle", "vid1").build_changes(video_doc, video_doc)


def test_channel_change():
    old = {
        "channel_id": "chan1",
        "channel_name": "Old Name",
        "channel_subs": 100,
        "channel_active": True,
    }
    new = old | {"channel_name": "New Name", "channel_subs": 120}
    changes = _tracker("channel", "chan1").build_changes(old, new)

    assert {i["field"] for i in changes} == {"channel_name", "channel_subs"}
    assert all(i["channel_id"] == "chan1" for i in changes)


def test_playlist_entry_count():
    old = {
        "playlist_id": "pl1",
        "playlist_name": "List",
        "playlist_channel_id": "chan1",
        "playlist_entries": [{"youtube_id": "a"}],
    }
    new = old | {
        "playlist_entries": [{"youtube_id": "a"}, {"youtube_id": "b"}]
    }
    changes = _tracker("playlist", "pl1").build_changes(old, new)

    assert len(changes) == 1
    assert changes[0]["field"] == "playlist_entry_count"
    assert changes[0]["old_num"] == 1
    assert changes[0]["new_num"] == 2
    assert changes[0]["channel_id"] == "chan1"


def test_published_representation_flip_is_not_a_change(video_doc):
    new = video_doc.copy()
    new["published"] = "2020-09-13"
    assert _tracker().build_changes(video_doc, new) == []


def test_published_real_change(video_doc):
    new = video_doc.copy()
    new["published"] = "2020-09-14"
    changes = _tracker().build_changes(video_doc, new)

    assert len(changes) == 1
    assert changes[0]["field"] == "published"
    assert changes[0]["old_num"] == 1600000000
    assert changes[0]["new_value"] == "2020-09-14"


def test_bulk_item_errors_are_reported(video_doc, capsys):
    failure = {
        "errors": True,
        "items": [
            {"index": {"error": {"type": "document_parsing_exception"}}}
        ],
    }
    with mock.patch(
        "common.src.history.ElasticWrap.post", return_value=(failure, 200)
    ):
        _tracker().track(video_doc, video_doc | {"title": "New"})

    assert "document_parsing_exception" in capsys.readouterr().out


def test_track_deactivation(video_doc, monkeypatch):
    written = []
    monkeypatch.setattr(
        HistoryTracker,
        "_upload",
        lambda self, changes: written.append(changes),
    )
    changes = track_deactivation("video", "vid1", video_doc)

    assert len(changes) == 1
    assert changes[0]["field"] == "active"
    assert changes[0]["old_value"] == "true"
    assert changes[0]["new_value"] == "false"
    assert written == [changes]


def test_track_never_raises(monkeypatch):
    def boom(self, changes):
        raise ConnectionError("es is down")

    monkeypatch.setattr(HistoryTracker, "_upload", boom)

    assert track_changes("video", "vid1", {"title": "a"}, {"title": "b"}) == []


@pytest.mark.parametrize(
    "value,expected_type",
    [
        ("text", "string"),
        (5, "number"),
        (1.5, "number"),
        (True, "bool"),
        (None, "null"),
        (["a"], "json"),
        ({"a": 1}, "json"),
        (MISSING, "missing"),
    ],
)
def test_encode_decode_roundtrip(value, expected_type):
    stored, value_type, _ = encode_value(value)
    assert value_type == expected_type
    assert decode_value(stored, value_type) == value


def test_decode_change():
    decoded = decode_change(
        {
            "field": "tags",
            "old_value": '["a"]',
            "old_value_type": "json",
            "new_value": '["a", "b"]',
            "new_value_type": "json",
        }
    )
    assert decoded["old_value"] == ["a"]
    assert decoded["new_value"] == ["a", "b"]


def test_query_filters():
    query = HistoryQuery(
        item_id="vid1",
        item_type="video",
        fields=["title"],
        since=100,
        until=200,
    ).build_query()
    must = query["bool"]["must"]

    assert {"term": {"item_id": {"value": "vid1"}}} in must
    assert {"term": {"item_type": {"value": "video"}}} in must
    assert {"terms": {"field": ["title"]}} in must
    assert {
        "range": {
            "timestamp": {"gte": 100, "lte": 200, "format": "epoch_second"}
        }
    } in must


def test_time_range_declares_epoch_second():
    query = HistoryQuery(item_id="vid1", since=1787000000).build_query()
    time_range = [
        i["range"]["timestamp"] for i in query["bool"]["must"] if "range" in i
    ][0]
    assert time_range["format"] == "epoch_second"


def test_no_time_range_without_cutoffs():
    must = HistoryQuery(item_id="vid1").build_query()["bool"]["must"]
    assert not [i for i in must if "range" in i]


def test_query_without_filters():
    assert HistoryQuery().build_query() == {"match_all": {}}
