# pylint: disable=protected-access

from types import SimpleNamespace

from download.src import yt_dlp_handler as handler_mod
from download.src.yt_dlp_handler import DownloadPostProcess, VideoDownloader
from downscale.src.constants import QUEUE_DOC_SOURCE_FIELDS
from downscale.src.queue_interact import DownscaleInteract


def a_video(youtube_id, channel_id, height):
    return {
        "youtube_id": youtube_id,
        "title": f"title of {youtube_id}",
        "channel": {"channel_id": channel_id, "channel_name": "a channel"},
        "vid_thumb_url": f"/thumb/{youtube_id}.jpg",
        "media_url": f"{channel_id}/{youtube_id}.mp4",
        "media_size": 1024,
        "streams": [
            {"type": "audio", "bitrate": 128000},
            {"type": "video", "height": height},
        ],
    }


def fake_interact(active=()):
    """returns (stand in, the list it records into)"""
    created = []

    class FakeInteract(DownscaleInteract):
        def create(self, doc):
            created.append(doc)
            return doc["youtube_id"]

        @staticmethod
        def build_queued_doc(
            youtube_id, video_json_data, current_height, target_height
        ):
            return {
                "youtube_id": youtube_id,
                "title": video_json_data["title"],
                "current_height": current_height,
                "target_height": target_height,
            }

        @staticmethod
        def get_active_for_video(youtube_id, exclude_id=None):
            return {"id": youtube_id} if youtube_id in active else None

    return FakeInteract, created


def make_handler(overwrites, candidates, add_metadata=True):
    """returns (stand in, the args the candidate query saw)"""
    seen_args = {}

    def _candidates(video_ids, targets):
        seen_args["video_ids"] = video_ids
        seen_args["targets"] = targets
        return candidates

    handler = SimpleNamespace(
        config={"downloads": {"add_metadata": add_metadata}},
        channel_overwrites=overwrites,
        VIDEO_QUEUE=DownloadPostProcess.VIDEO_QUEUE,
        _get_downscale_candidates=_candidates,
    )
    return handler, seen_args


def patch_env(monkeypatch, interact, video_ids=("vid1",)):
    """returns the list dispatch calls land in"""
    dispatched = []
    monkeypatch.setattr(
        handler_mod,
        "RedisQueue",
        lambda name: SimpleNamespace(get_all=lambda: list(video_ids)),
    )
    monkeypatch.setattr(handler_mod, "DownscaleInteract", interact)
    monkeypatch.setattr(
        handler_mod,
        "dispatch_pending_downscales",
        lambda: dispatched.append(True),
    )
    return dispatched


class TestAutoDownscale:
    def test_queues_a_video_above_the_target(self, monkeypatch):
        interact, created = fake_interact()
        dispatched = patch_env(monkeypatch, interact)
        handler, _ = make_handler(
            {"chan1": {"downscale_target_height": 1080}},
            [a_video("vid1", "chan1", 2160)],
        )

        DownloadPostProcess.auto_downscale(handler)

        assert len(created) == 1
        assert created[0]["youtube_id"] == "vid1"
        assert created[0]["current_height"] == 2160
        assert created[0]["target_height"] == 1080
        assert dispatched == [True]

    def test_skips_a_video_already_at_or_below_the_target(self, monkeypatch):
        interact, created = fake_interact()
        dispatched = patch_env(
            monkeypatch, interact, video_ids=("at", "below")
        )
        handler, _ = make_handler(
            {"chan1": {"downscale_target_height": 1080}},
            [a_video("at", "chan1", 1080), a_video("below", "chan1", 720)],
        )

        DownloadPostProcess.auto_downscale(handler)

        assert created == []
        assert dispatched == []

    def test_queues_anything_above_target_however_close(self, monkeypatch):
        interact, created = fake_interact()
        patch_env(monkeypatch, interact)
        handler, _ = make_handler(
            {"chan1": {"downscale_target_height": 1080}},
            [a_video("vid1", "chan1", 1440)],
        )

        DownloadPostProcess.auto_downscale(handler)

        assert [i["youtube_id"] for i in created] == ["vid1"]

    def test_skips_a_video_that_already_has_a_job(self, monkeypatch):
        interact, created = fake_interact(active={"vid1"})
        dispatched = patch_env(monkeypatch, interact)
        handler, _ = make_handler(
            {"chan1": {"downscale_target_height": 1080}},
            [a_video("vid1", "chan1", 2160)],
        )

        DownloadPostProcess.auto_downscale(handler)

        assert created == []
        assert dispatched == []

    def test_skips_a_video_with_no_video_stream(self, monkeypatch):
        interact, created = fake_interact()
        patch_env(monkeypatch, interact)
        audio_only = a_video("vid1", "chan1", 2160)
        audio_only["streams"] = [{"type": "audio", "bitrate": 128000}]
        handler, _ = make_handler(
            {"chan1": {"downscale_target_height": 1080}}, [audio_only]
        )

        DownloadPostProcess.auto_downscale(handler)

        assert created == []

    def test_dispatches_once_for_a_whole_batch(self, monkeypatch):
        interact, created = fake_interact()
        dispatched = patch_env(
            monkeypatch, interact, video_ids=("a", "b", "c")
        )
        handler, _ = make_handler(
            {"chan1": {"downscale_target_height": 720}},
            [
                a_video("a", "chan1", 2160),
                a_video("b", "chan1", 1080),
                a_video("c", "chan1", 1440),
            ],
        )

        DownloadPostProcess.auto_downscale(handler)

        assert len(created) == 3
        assert dispatched == [True]

    def test_uses_the_target_of_each_video_s_own_channel(self, monkeypatch):
        interact, created = fake_interact()
        patch_env(monkeypatch, interact, video_ids=("a", "b"))
        handler, _ = make_handler(
            {
                "chan1": {"downscale_target_height": 1080},
                "chan2": {"downscale_target_height": 480},
            },
            [a_video("a", "chan1", 2160), a_video("b", "chan2", 2160)],
        )

        DownloadPostProcess.auto_downscale(handler)

        by_id = {i["youtube_id"]: i["target_height"] for i in created}
        assert by_id == {"a": 1080, "b": 480}

    def test_does_nothing_when_no_channel_has_a_target(self, monkeypatch):
        interact, created = fake_interact()
        dispatched = patch_env(monkeypatch, interact)
        handler, seen = make_handler(
            {"chan1": {"index_playlists": True}},
            [a_video("vid1", "chan1", 2160)],
        )

        DownloadPostProcess.auto_downscale(handler)

        assert created == []
        assert dispatched == []
        assert seen == {}

    def test_ignores_a_channel_whose_target_is_cleared(self, monkeypatch):
        interact, created = fake_interact()
        handler, seen = make_handler(
            {"chan1": {"downscale_target_height": None}},
            [a_video("vid1", "chan1", 2160)],
        )
        patch_env(monkeypatch, interact)

        DownloadPostProcess.auto_downscale(handler)

        assert created == []
        assert seen == {}

    def test_does_nothing_when_nothing_was_downloaded(self, monkeypatch):
        interact, created = fake_interact()
        patch_env(monkeypatch, interact, video_ids=())
        handler, seen = make_handler(
            {"chan1": {"downscale_target_height": 1080}},
            [a_video("vid1", "chan1", 2160)],
        )

        DownloadPostProcess.auto_downscale(handler)

        assert created == []
        assert seen == {}

    def test_looks_up_only_the_new_videos_of_targeted_channels(
        self, monkeypatch
    ):
        interact, _ = fake_interact()
        patch_env(monkeypatch, interact, video_ids=("a", "b"))
        handler, seen = make_handler(
            {"chan1": {"downscale_target_height": 1080}}, []
        )

        DownloadPostProcess.auto_downscale(handler)

        assert seen["video_ids"] == ["a", "b"]
        assert seen["targets"] == {"chan1": 1080}

    def test_leaves_queuing_to_the_download_loop_without_embedding(
        self, monkeypatch
    ):
        interact, created = fake_interact()
        dispatched = patch_env(monkeypatch, interact)
        handler, seen = make_handler(
            {"chan1": {"downscale_target_height": 1080}},
            [a_video("vid1", "chan1", 2160)],
            add_metadata=False,
        )

        DownloadPostProcess.auto_downscale(handler)

        assert created == []
        assert dispatched == []
        assert seen == {}


def a_downloader(monkeypatch, overwrites, add_metadata=False):
    monkeypatch.setattr(
        handler_mod, "get_channel_overwrites", lambda: overwrites
    )
    return SimpleNamespace(
        config={"downloads": {"add_metadata": add_metadata}},
        channel_overwrites={},
    )


class TestQueueOnDownload:
    def test_queues_the_video_as_soon_as_it_is_archived(self, monkeypatch):
        interact, created = fake_interact()
        dispatched = patch_env(monkeypatch, interact)
        downloader = a_downloader(
            monkeypatch, {"chan1": {"downscale_target_height": 720}}
        )

        VideoDownloader._auto_downscale(
            downloader, a_video("vid1", "chan1", 1080)
        )

        assert [i["youtube_id"] for i in created] == ["vid1"]
        assert created[0]["target_height"] == 720
        assert dispatched == [True]

    def test_waits_for_post_processing_when_embedding(self, monkeypatch):
        interact, created = fake_interact()
        dispatched = patch_env(monkeypatch, interact)
        downloader = a_downloader(
            monkeypatch,
            {"chan1": {"downscale_target_height": 720}},
            add_metadata=True,
        )

        VideoDownloader._auto_downscale(
            downloader, a_video("vid1", "chan1", 1080)
        )

        assert created == []
        assert dispatched == []

    def test_skips_a_channel_without_a_target(self, monkeypatch):
        interact, created = fake_interact()
        dispatched = patch_env(monkeypatch, interact)
        downloader = a_downloader(
            monkeypatch, {"chan2": {"downscale_target_height": 720}}
        )

        VideoDownloader._auto_downscale(
            downloader, a_video("vid1", "chan1", 1080)
        )

        assert created == []
        assert dispatched == []

    def test_skips_a_video_that_already_has_a_job(self, monkeypatch):
        interact, created = fake_interact(active={"vid1"})
        dispatched = patch_env(monkeypatch, interact)
        downloader = a_downloader(
            monkeypatch, {"chan1": {"downscale_target_height": 720}}
        )

        VideoDownloader._auto_downscale(
            downloader, a_video("vid1", "chan1", 1080)
        )

        assert created == []
        assert dispatched == []

    def test_a_failed_queue_write_does_not_stop_the_download_run(
        self, monkeypatch
    ):
        interact, _ = fake_interact()

        class FailingInteract(interact):
            def create(self, doc):
                raise ValueError("failed to add item to index")

        dispatched = patch_env(monkeypatch, FailingInteract)
        downloader = a_downloader(
            monkeypatch, {"chan1": {"downscale_target_height": 720}}
        )

        VideoDownloader._auto_downscale(
            downloader, a_video("vid1", "chan1", 1080)
        )

        assert dispatched == []

    def test_the_download_loop_queues_after_the_move(self, monkeypatch):
        ran = []
        items = iter(
            [
                {
                    "youtube_id": "vid1",
                    "channel_id": "chan1",
                    "vid_type": "videos",
                }
            ]
            + [False]
        )
        handler = SimpleNamespace(
            config={},
            task=SimpleNamespace(is_stopped=lambda: False),
            _get_next=lambda auto_only: next(items),
            _reset_auto=lambda: None,
            _notify=lambda *a, **kw: None,
            _dl_single_vid=lambda youtube_id, channel_id: True,
            move_to_archive=lambda vid_dict: ran.append("move"),
            _auto_downscale=lambda vid_dict: ran.append(
                ("downscale", vid_dict["youtube_id"])
            ),
            CHANNEL_QUEUE="c",
            VIDEO_QUEUE="v",
        )
        monkeypatch.setattr(
            handler_mod,
            "index_new_video",
            lambda youtube_id, video_type: {"youtube_id": youtube_id},
        )
        monkeypatch.setattr(
            handler_mod,
            "RedisQueue",
            lambda name: SimpleNamespace(add=lambda item: None),
        )
        monkeypatch.setattr(
            handler_mod,
            "PendingInteract",
            lambda youtube_id: SimpleNamespace(clear_indexed=lambda: None),
        )
        monkeypatch.setattr(
            handler_mod,
            "DownloadPostProcess",
            lambda task: SimpleNamespace(run=lambda: ran.append("post")),
        )

        assert VideoDownloader.run_queue(handler) == (1, 0)
        assert ran == ["move", ("downscale", "vid1"), "post"]


class TestCandidateQuery:
    def test_scopes_the_query_to_the_new_ids_and_channels(self, monkeypatch):
        captured = {}

        class FakePaginate:
            def __init__(self, index_name, data, **kwargs):
                captured["index"] = index_name
                captured["data"] = data

            @staticmethod
            def get_results():
                return []

        monkeypatch.setattr(handler_mod, "IndexPaginate", FakePaginate)

        DownloadPostProcess._get_downscale_candidates(
            ["a", "b"], {"chan1": 1080, "chan2": 720}
        )

        must = captured["data"]["query"]["bool"]["must"]
        assert captured["index"] == "ta_video"
        assert {"ids": {"values": ["a", "b"]}} in must
        assert {"terms": {"channel.channel_id": ["chan1", "chan2"]}} in must

    def test_asks_for_every_field_build_queued_doc_reads(self, monkeypatch):
        captured = {}

        class FakePaginate:
            def __init__(self, index_name, data, **kwargs):
                captured["data"] = data

            @staticmethod
            def get_results():
                return []

        monkeypatch.setattr(handler_mod, "IndexPaginate", FakePaginate)

        DownloadPostProcess._get_downscale_candidates(["a"], {"chan1": 1080})
        fetched = captured["data"]["_source"]

        assert fetched == QUEUE_DOC_SOURCE_FIELDS

        full = a_video("a", "c1", 2160)
        doc = DownscaleInteract.build_queued_doc(
            youtube_id="a",
            video_json_data={k: v for k, v in full.items() if k in fetched},
            current_height=2160,
            target_height=1080,
        )

        assert doc["youtube_id"] == "a"
        assert doc["channel_id"] == "c1"
        assert doc["status"] == "queued"
        assert doc["target_height"] == 1080
        assert doc["original_size"] == 1024
