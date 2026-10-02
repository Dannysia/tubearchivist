"""test the batch downscale of one channel"""

import pytest
from downscale.src import channel_batch
from downscale.src.channel_batch import ChannelDownscale
from downscale.src.queue_interact import DownscaleInteract


def _video(youtube_id, height):
    streams = [{"type": "video", "height": height}] if height else []
    return {"youtube_id": youtube_id, "streams": streams}


class FakeTask:
    def __init__(self, stop_after=None):
        self.progress = []
        self.stop_after = stop_after

    def is_stopped(self):
        return self.stop_after is not None and (
            len(self.progress) >= self.stop_after
        )

    def send_progress(self, message_lines, progress=None):
        self.progress.append(progress)


@pytest.fixture
def world(monkeypatch):
    state = {"videos": [], "active": set(), "created": [], "dispatched": 0}

    monkeypatch.setattr(
        ChannelDownscale, "_get_videos", lambda self: list(state["videos"])
    )

    class Interact(DownscaleInteract):
        @staticmethod
        def get_active_for_video(youtube_id):
            return (
                {"id": youtube_id} if youtube_id in state["active"] else None
            )

        @staticmethod
        def build_queued_doc(**kwargs):
            return kwargs

        def create(self, doc):
            state["created"].append(doc["youtube_id"])
            return doc["youtube_id"]

    monkeypatch.setattr(channel_batch, "DownscaleInteract", Interact)

    def dispatch():
        state["dispatched"] += 1

    monkeypatch.setattr(channel_batch, "dispatch_pending_downscales", dispatch)
    return state


def test_queues_only_videos_above_the_target(world):
    world["videos"] = [
        _video("tall", 1080),
        _video("equal", 480),
        _video("short", 360),
        _video("no_streams", None),
    ]

    handler = ChannelDownscale("UC1", 480)
    handler.run()

    assert handler.queued == ["tall"]
    assert world["created"] == ["tall"]
    assert world["dispatched"] == 1


def test_a_video_with_a_job_is_skipped(world):
    world["videos"] = [_video("busy", 1080), _video("free", 1080)]
    world["active"] = {"busy"}

    handler = ChannelDownscale("UC1", 480)
    handler.run()

    assert handler.queued == ["free"]
    assert handler.skipped == ["busy"]


def test_nothing_queued_dispatches_nothing(world):
    world["videos"] = [_video("short", 360)]

    ChannelDownscale("UC1", 480).run()

    assert world["dispatched"] == 0


def test_a_stop_ends_the_batch_and_still_dispatches(world):
    world["videos"] = [_video(f"v{i}", 1080) for i in range(5)]
    task = FakeTask(stop_after=2)

    handler = ChannelDownscale("UC1", 480, task=task)
    handler.run()

    assert handler.queued == ["v0", "v1"]
    assert world["dispatched"] == 1


@pytest.mark.parametrize("skip_inactive", [False, True])
def test_skip_inactive_leaves_out_only_inactive_videos(
    monkeypatch, skip_inactive
):
    seen = {}

    class Paginate:
        def __init__(self, index, data, **kwargs):
            seen["query"] = data["query"]

        def get_results(self):
            return []

    monkeypatch.setattr(channel_batch, "IndexPaginate", Paginate)

    ChannelDownscale("UC1", 480, skip_inactive=skip_inactive)._get_videos()

    query = seen["query"]["bool"]
    assert query["must"] == [
        {"term": {"channel.channel_id": {"value": "UC1"}}}
    ]
    expected = [{"term": {"active": False}}] if skip_inactive else None
    assert query.get("must_not") == expected
