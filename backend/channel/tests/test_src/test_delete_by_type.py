# pylint: disable=protected-access
# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from channel.serializers import ChannelVideoDeleteQuerySerializer
from channel.src import index as channel_index
from channel.src.index import ChannelVideoTypeDelete
from common.src.es_connect import ElasticUnavailable, IndexPaginate


class TestDeleteQuerySerializer:
    def test_type_is_required(self):
        serializer = ChannelVideoDeleteQuerySerializer(data={})
        assert not serializer.is_valid()
        assert "vid_type" in serializer.errors

    @pytest.mark.parametrize("vid_type", ["videos", "streams", "shorts"])
    def test_known_types_pass(self, vid_type):
        serializer = ChannelVideoDeleteQuerySerializer(
            data={"vid_type": vid_type}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["vid_type"] == vid_type

    @pytest.mark.parametrize("vid_type", ["", "all", "unknown", "Shorts"])
    def test_anything_else_fails(self, vid_type):
        serializer = ChannelVideoDeleteQuerySerializer(
            data={"vid_type": vid_type}
        )
        assert not serializer.is_valid()


class TestGetVideoIds:
    def test_scoped_to_channel_and_type(self, monkeypatch):
        captured = {}

        class FakePaginate:
            def __init__(self, index, data):
                captured["index"] = index
                captured["data"] = data

            def get_results(self):
                return [{"youtube_id": "a"}, {"youtube_id": "b"}]

        monkeypatch.setattr(channel_index, "IndexPaginate", FakePaginate)

        handler = ChannelVideoTypeDelete("UC1", "shorts")
        assert handler.get_video_ids() == ["a", "b"]

        assert captured["index"] == "ta_video"
        must = captured["data"]["query"]["bool"]["must"]
        assert {"term": {"channel.channel_id": {"value": "UC1"}}} in must
        assert {"term": {"vid_type": {"value": "shorts"}}} in must
        assert len(must) == 2


class TestDelete:
    @staticmethod
    def _patch(monkeypatch, ids, deleter):
        monkeypatch.setattr(
            ChannelVideoTypeDelete, "get_video_ids", lambda self: ids
        )
        import video.src.index as video_index

        monkeypatch.setattr(video_index, "YoutubeVideo", deleter)

    def test_deletes_every_video_of_the_type(self, monkeypatch):
        deleted = []

        def deleter(youtube_id):
            return SimpleNamespace(
                delete_media_file=lambda: deleted.append(youtube_id)
            )

        self._patch(monkeypatch, ["a", "b", "c"], deleter)

        assert ChannelVideoTypeDelete("UC1", "shorts").delete() == 3
        assert deleted == ["a", "b", "c"]

    def test_missing_video_does_not_abort_the_rest(self, monkeypatch):
        deleted = []

        def deleter(youtube_id):
            def delete_media_file():
                if youtube_id == "b":
                    raise FileNotFoundError
                deleted.append(youtube_id)

            return SimpleNamespace(delete_media_file=delete_media_file)

        self._patch(monkeypatch, ["a", "b", "c"], deleter)

        assert ChannelVideoTypeDelete("UC1", "shorts").delete() == 2
        assert deleted == ["a", "c"]

    def test_stop_halts_the_delete(self, monkeypatch):
        deleted = []

        def deleter(youtube_id):
            return SimpleNamespace(
                delete_media_file=lambda: deleted.append(youtube_id)
            )

        self._patch(monkeypatch, ["a", "b", "c", "d"], deleter)

        checks = iter([False, False, True])
        task = SimpleNamespace(
            is_stopped=lambda: next(checks),
            send_progress=lambda message, progress=False: None,
        )

        assert ChannelVideoTypeDelete("UC1", "shorts", task=task).delete() == 2
        assert deleted == ["a", "b"]

    def test_reports_progress_per_video(self, monkeypatch):
        sent = []

        def deleter(youtube_id):
            return SimpleNamespace(delete_media_file=lambda: None)

        self._patch(monkeypatch, ["a", "b"], deleter)

        task = SimpleNamespace(
            is_stopped=lambda: False,
            send_progress=lambda message, progress=False: sent.append(
                (message, progress)
            ),
        )
        ChannelVideoTypeDelete("UC1", "shorts", task=task).delete()

        assert sent == [
            (["Deleting shorts 1/2"], 0.5),
            (["Deleting shorts 2/2"], 1.0),
        ]


VIDEO_DOC = {
    "youtube_id": "abc",
    "title": "Some Short",
    "published": 1717607899,
    "vid_type": "shorts",
    "vid_thumb_url": "https://i.ytimg.com/vi/abc/default.jpg",
    "player": {"duration": 42, "duration_str": "42s"},
    "channel": {"channel_id": "UC1", "channel_name": "Some Channel"},
}


class TestBuildIgnoreDoc:
    def test_maps_every_field_the_queue_needs(self):
        doc = ChannelVideoTypeDelete._build_ignore_doc(VIDEO_DOC)

        assert doc["youtube_id"] == "abc"
        assert doc["channel_id"] == "UC1"
        assert doc["channel_name"] == "Some Channel"
        assert doc["channel_indexed"] is True
        assert doc["duration"] == "42s"
        assert doc["published"] == 1717607899
        assert doc["title"] == "Some Short"
        assert doc["vid_type"] == "shorts"
        assert doc["status"] == "ignore"
        assert doc["auto_start"] is False

    def test_satisfies_the_download_item_serializer(self):
        from download.serializers import DownloadItemSerializer

        doc = ChannelVideoTypeDelete._build_ignore_doc(VIDEO_DOC)
        serializer = DownloadItemSerializer(data=doc)
        assert serializer.is_valid(), serializer.errors

    def test_a_partial_video_document_is_refused(self):
        doc = ChannelVideoTypeDelete._build_ignore_doc(
            {**VIDEO_DOC, "channel": {}}
        )
        assert doc is None

    def test_a_blank_thumb_url_is_not_a_refusal(self):
        doc = ChannelVideoTypeDelete._build_ignore_doc(
            {**VIDEO_DOC, "vid_thumb_url": ""}
        )
        assert doc is not None
        assert doc["vid_thumb_url"] is None

    def test_missing_duration_does_not_break_it(self):
        doc = ChannelVideoTypeDelete._build_ignore_doc(
            {**VIDEO_DOC, "player": {}}
        )
        assert doc["duration"] == "NA"


class TestDeleteWithIgnore:
    @staticmethod
    def _patch(monkeypatch, docs):
        monkeypatch.setattr(
            ChannelVideoTypeDelete,
            "get_video_ids",
            lambda self: [d["youtube_id"] for d in docs],
        )
        import video.src.index as video_index

        by_id = {d["youtube_id"]: d for d in docs}

        def deleter(youtube_id):
            video = SimpleNamespace(json_data=None)
            video.get_from_es = lambda: setattr(
                video, "json_data", by_id[youtube_id]
            )
            video.delete_media_file = lambda: None
            return video

        monkeypatch.setattr(video_index, "YoutubeVideo", deleter)

    def test_a_refused_doc_is_reported_not_just_dropped(self, monkeypatch):
        broken = {**VIDEO_DOC, "youtube_id": "def", "channel": {}}
        self._patch(monkeypatch, [VIDEO_DOC, broken])
        written = []
        monkeypatch.setattr(
            ChannelVideoTypeDelete,
            "_write_ignore",
            staticmethod(lambda d: written.append(d)),
        )
        handler = ChannelVideoTypeDelete("UC1", "shorts", ignore=True)

        assert handler.delete() == 2, "both videos still go"
        assert [d["youtube_id"] for d in written] == ["abc"]
        assert handler.not_ignored == ["def"]

    def test_nothing_refused_reports_nothing(self, monkeypatch):
        self._patch(monkeypatch, [VIDEO_DOC])
        monkeypatch.setattr(
            ChannelVideoTypeDelete,
            "_write_ignore",
            staticmethod(lambda d: None),
        )
        handler = ChannelVideoTypeDelete("UC1", "shorts", ignore=True)
        handler.delete()

        assert handler.not_ignored == []

    def test_writes_one_ignore_entry_per_video(self, monkeypatch):
        written = []
        self._patch(
            monkeypatch,
            [VIDEO_DOC, {**VIDEO_DOC, "youtube_id": "def"}],
        )
        monkeypatch.setattr(
            ChannelVideoTypeDelete,
            "_write_ignore",
            staticmethod(lambda d: written.append(d)),
        )

        handler = ChannelVideoTypeDelete("UC1", "shorts", ignore=True)
        assert handler.delete() == 2
        assert [d["youtube_id"] for d in written] == ["abc", "def"]
        assert {d["status"] for d in written} == {"ignore"}

    def test_plain_delete_writes_nothing(self, monkeypatch):
        written = []
        self._patch(monkeypatch, [VIDEO_DOC])
        monkeypatch.setattr(
            ChannelVideoTypeDelete,
            "_write_ignore",
            staticmethod(lambda d: written.append(d)),
        )

        assert ChannelVideoTypeDelete("UC1", "shorts").delete() == 1
        assert written == []

    def test_stopped_run_still_ignores_what_it_deleted(self, monkeypatch):
        written = []
        docs = [
            VIDEO_DOC,
            {**VIDEO_DOC, "youtube_id": "def"},
            {**VIDEO_DOC, "youtube_id": "ghi"},
        ]
        self._patch(monkeypatch, docs)
        monkeypatch.setattr(
            ChannelVideoTypeDelete,
            "_write_ignore",
            staticmethod(lambda d: written.append(d)),
        )

        checks = iter([False, False, True])
        task = SimpleNamespace(
            is_stopped=lambda: next(checks),
            send_progress=lambda message, progress=False: None,
        )
        handler = ChannelVideoTypeDelete(
            "UC1", "shorts", task=task, ignore=True
        )
        assert handler.delete() == 2
        assert [d["youtube_id"] for d in written] == ["abc", "def"]


class TestWriteIgnore:
    def test_the_row_is_put_under_the_video_id(self, monkeypatch):
        captured = {}

        class FakeWrap:
            def __init__(self, path):
                captured["path"] = path

            def put(self, data=False, refresh=False):
                captured["data"] = data
                return {}, 201

        monkeypatch.setattr(channel_index, "ElasticWrap", FakeWrap)
        doc = ChannelVideoTypeDelete._build_ignore_doc(VIDEO_DOC)

        ChannelVideoTypeDelete._write_ignore(doc)

        assert captured["path"] == "ta_download/_doc/abc"
        assert captured["data"]["status"] == "ignore"


class TestDeleteOrdering:
    @staticmethod
    def _patch(monkeypatch, ids, order, write=lambda doc: None):
        monkeypatch.setattr(
            ChannelVideoTypeDelete, "get_video_ids", lambda self: ids
        )
        monkeypatch.setattr(
            ChannelVideoTypeDelete, "_write_ignore", staticmethod(write)
        )
        import video.src.index as video_index

        def deleter(youtube_id):
            video = SimpleNamespace(json_data=None)
            video.get_from_es = lambda: setattr(
                video, "json_data", {**VIDEO_DOC, "youtube_id": youtube_id}
            )
            video.delete_media_file = lambda: order.append(
                ("delete", youtube_id)
            )
            return video

        monkeypatch.setattr(video_index, "YoutubeVideo", deleter)

    def test_the_row_is_written_before_that_video_is_deleted(
        self, monkeypatch
    ):
        order = []

        def write(doc):
            order.append(("write", doc["youtube_id"]))

        self._patch(monkeypatch, ["a", "b"], order, write)

        ChannelVideoTypeDelete("UC1", "shorts", ignore=True).delete()

        assert order == [
            ("write", "a"),
            ("delete", "a"),
            ("write", "b"),
            ("delete", "b"),
        ]

    def test_a_video_whose_row_fails_is_kept(self, monkeypatch):
        order = []

        def write(doc):
            if doc["youtube_id"] == "b":
                raise ElasticUnavailable("es answered 503")

            order.append(("write", doc["youtube_id"]))

        self._patch(monkeypatch, ["a", "b", "c"], order, write)
        handler = ChannelVideoTypeDelete("UC1", "shorts", ignore=True)

        assert handler.delete() == 2
        assert ("delete", "b") not in order
        assert handler.failed == ["b"]
        assert handler.ignored == 2

    def test_a_failed_delete_does_not_abandon_the_rest(self, monkeypatch):
        order = []
        self._patch(monkeypatch, ["a", "b", "c"], order)
        import video.src.index as video_index

        def deleter(youtube_id):
            video = SimpleNamespace(json_data=VIDEO_DOC)
            video.get_from_es = lambda: None

            def delete_media_file():
                if youtube_id == "b":
                    raise PermissionError("read-only file system")
                order.append(youtube_id)

            video.delete_media_file = delete_media_file
            return video

        monkeypatch.setattr(video_index, "YoutubeVideo", deleter)
        handler = ChannelVideoTypeDelete("UC1", "shorts")

        assert handler.delete() == 2
        assert order == ["a", "c"]
        assert handler.failed == ["b"]

    def test_a_dangling_playlist_reference_is_survivable(self, monkeypatch):
        order = []
        self._patch(monkeypatch, ["a", "b"], order)
        import video.src.index as video_index

        def deleter(youtube_id):
            video = SimpleNamespace(json_data=VIDEO_DOC)
            video.get_from_es = lambda: None

            def delete_media_file():
                if youtube_id == "a":
                    raise TypeError("'NoneType' object is not subscriptable")
                order.append(youtube_id)

            video.delete_media_file = delete_media_file
            return video

        monkeypatch.setattr(video_index, "YoutubeVideo", deleter)
        handler = ChannelVideoTypeDelete("UC1", "shorts")

        assert handler.delete() == 1
        assert order == ["b"]
        assert handler.failed == ["a"]
