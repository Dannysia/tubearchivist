"""every paced loop must leave itself when the wait refuses

countdown_sleep returns False when a stop request cut the wait short,
and the wait *is* the rate limit - carrying on after a shortened one
hits youtube harder than a normal pass does. Nothing enforced that per
site, so a loop could quietly drop the break and every other test would
still pass. These drive each real loop with a wait that always refuses.

The message shape tests are the other half: the countdown line goes
*under* whatever the loop is working on, never replacing it.
"""

# flake8: noqa: E402

import os
from itertools import count
from types import SimpleNamespace
from unittest import mock

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.src import filesystem as filesystem_mod
from appsettings.src.filesystem import Scanner
from channel.src import index as channel_mod
from channel.src.index import YoutubeChannel
from download.src import queue as queue_mod
from download.src import yt_dlp_handler as post_mod
from download.src.queue import PendingList
from download.src.yt_dlp_handler import DownloadPostProcess, VideoDownloader
from video.src import comments as comments_mod
from video.src.comments import CommentList

CONFIG = {"downloads": {"sleep_interval": 10}}


def capture_task():
    """a task that records the lines that reach it"""
    sent = []
    task = SimpleNamespace(
        is_stopped=lambda: False,
        send_progress=lambda *a, **kw: sent.append(
            a[0] if a else kw.get("message_lines")
        ),
    )
    return sent, task


def queue_of_one(length=1):
    """one item comes off, then nothing; length is what is left after"""
    items = iter([("abc", 1), (None, None)])
    return SimpleNamespace(
        key="q",
        max_score=lambda: 1,
        get_next=lambda: next(items),
        length=lambda: length,
    )


def endless_queue():
    """never drains, so only a break can end the loop

    A queue that runs dry ends the loop by itself, which is why a stop
    test against one passes whether or not the break is there.
    """
    counter = count(1)

    def get_next():
        nxt = next(counter)
        assert nxt < 50, "loop did not break on the refusal"
        return f"id{nxt}", nxt

    return SimpleNamespace(
        key="q", max_score=lambda: 99, get_next=get_next, length=lambda: 99
    )


def refuse(monkeypatch, module):
    """a wait that always reports a stop"""
    monkeypatch.setattr(module, "countdown_sleep", lambda *a, **kw: False)


def record(monkeypatch, module, seen):
    """a wait that reports what it was asked to narrate"""

    def fake(config, task, notify=None, label=""):
        if notify:
            notify(f"Waiting 8s before {label}")

        seen.append(label)
        return True

    monkeypatch.setattr(module, "countdown_sleep", fake)


class TestCommentIndex:
    """video/src/comments.py CommentList.index"""

    @staticmethod
    def _handler(task, monkeypatch, length=1):
        monkeypatch.setattr(
            comments_mod, "RedisQueue", lambda name: queue_of_one(length)
        )
        monkeypatch.setattr(
            comments_mod,
            "Comments",
            lambda youtube_id, config=None, task=None: SimpleNamespace(
                build_json=lambda: None, json_data=None
            ),
        )
        handler = SimpleNamespace(COMMENT_QUEUE="q", config=CONFIG, task=task)
        handler.notify = lambda *a, **kw: CommentList.notify(handler, *a, **kw)
        handler._wait_for_next = lambda *a: CommentList._wait_for_next(
            handler, *a
        )

        return handler

    def test_a_stop_leaves_the_loop(self, monkeypatch):
        indexed = []
        _, task = capture_task()
        handler = self._handler(task, monkeypatch)
        monkeypatch.setattr(
            comments_mod, "RedisQueue", lambda name: endless_queue()
        )
        monkeypatch.setattr(
            comments_mod,
            "Comments",
            lambda youtube_id, config=None, task=None: indexed.append(
                youtube_id
            )
            or SimpleNamespace(build_json=lambda: None, json_data=None),
        )
        refuse(monkeypatch, comments_mod)

        assert CommentList.index(handler) is False, "must report the stop"
        assert len(indexed) == 1, "one item, then out"

    def test_countdown_goes_under_the_counter(self, monkeypatch):
        sent, task = capture_task()
        handler = self._handler(task, monkeypatch, length=4)
        seen = []
        record(monkeypatch, comments_mod, seen)

        CommentList.index(handler)

        assert seen == ["next video"]
        assert sent[-1] == [
            "Add comments for new videos 1/1",
            "Waiting 8s before next video",
        ]

    def test_drained_queue_says_nothing(self, monkeypatch):
        _, task = capture_task()
        handler = self._handler(task, monkeypatch, length=0)
        seen = []
        record(monkeypatch, comments_mod, seen)

        CommentList.index(handler)

        assert seen == [""], "the wait happens, with no next video named"


class TestChannelPlaylistIndex:
    """channel/src/index.py YoutubeChannel.index_channel_playlists"""

    @staticmethod
    def _handler(task, playlists):
        handler = SimpleNamespace(
            youtube_id="UC1",
            config=CONFIG,
            task=task,
            json_data={"channel_name": "Some Channel"},
            all_playlists=playlists,
            get_from_es=lambda: None,
            _index_single_playlist=lambda playlist: None,
        )
        handler.get_all_playlists = lambda: None
        handler._notify_single_playlist = (
            lambda *a, **kw: YoutubeChannel._notify_single_playlist(
                handler, *a, **kw
            )
        )
        handler._wait_for_next_playlist = (
            lambda *a: YoutubeChannel._wait_for_next_playlist(handler, *a)
        )

        return handler

    def test_a_stop_leaves_the_loop(self, monkeypatch):
        sent, task = capture_task()
        handler = self._handler(task, [("p1", "One"), ("p2", "Two")])
        refuse(monkeypatch, channel_mod)

        YoutubeChannel.index_channel_playlists(handler)

        # the first playlist's own line, and nothing from the second
        assert not any("2/2" in line for msg in sent for line in msg)

    def test_countdown_goes_under_the_counter(self, monkeypatch):
        sent, task = capture_task()
        handler = self._handler(task, [("p1", "One"), ("p2", "Two")])
        seen = []
        record(monkeypatch, channel_mod, seen)

        YoutubeChannel.index_channel_playlists(handler)

        # only one wait, after the first of two: nothing follows the
        # last playlist, index_channel_playlists is the whole task
        assert seen == ["next playlist"]
        # sent[0] is the "Looking for Playlists" preamble
        assert sent[2] == [
            "Some Channel: Scanning channel for playlists",
            "Progress: 1/2",
            "Waiting 8s before next playlist",
        ]


class TestFilesystemScan:
    """appsettings/src/filesystem.py Scanner.index"""

    @staticmethod
    def _handler(task, to_index):
        handler = SimpleNamespace(
            VIDEOS="/youtube",
            config=CONFIG,
            task=task,
            to_index=to_index,
            _index_one=lambda file_path, youtube_id: True,
        )
        handler._notify = lambda *a, **kw: Scanner._notify(handler, *a, **kw)
        handler._wait_for_next = lambda *a: Scanner._wait_for_next(handler, *a)

        return handler

    def test_a_stop_leaves_the_loop(self, monkeypatch):
        sent, task = capture_task()
        handler = self._handler(task, [("a", "a.mp4"), ("b", "b.mp4")])
        refuse(monkeypatch, filesystem_mod)

        Scanner.index(handler)

        assert not any("2/2" in line for msg in sent for line in msg)

    def test_countdown_goes_under_the_counter(self, monkeypatch):
        sent, task = capture_task()
        handler = self._handler(task, [("a", "a.mp4"), ("b", "b.mp4")])
        seen = []
        record(monkeypatch, filesystem_mod, seen)

        Scanner.index(handler)

        assert seen == ["next video", ""], "last one names nothing"
        assert sent[1] == [
            "Index missing video a, 1/2",
            "Waiting 8s before next video",
        ]


class TestPostProcessPlaylists:
    """download/src/yt_dlp_handler.py DownloadPostProcess.refresh_playlist"""

    @staticmethod
    def _handler(task, monkeypatch, length=1):
        monkeypatch.setattr(
            post_mod, "RedisQueue", lambda name: queue_of_one(length)
        )
        monkeypatch.setattr(
            post_mod,
            "YoutubePlaylist",
            lambda playlist_id: SimpleNamespace(
                update_playlist=lambda skip_on_empty=False: True,
                json_data={
                    "playlist_channel": "Some Channel",
                    "playlist_name": "Some Playlist",
                },
            ),
        )
        handler = SimpleNamespace(
            PLAYLIST_QUEUE="q",
            config=CONFIG,
            task=task,
            add_playlists_to_refresh=lambda: True,
        )
        handler._notify_playlist = (
            lambda *a, **kw: DownloadPostProcess._notify_playlist(
                handler, *a, **kw
            )
        )
        handler._wait_for_next_playlist = (
            lambda *a: DownloadPostProcess._wait_for_next_playlist(handler, *a)
        )
        handler._refresh_one_playlist = (
            lambda *a: DownloadPostProcess._refresh_one_playlist(handler, *a)
        )

        return handler

    def test_a_stop_leaves_the_loop(self, monkeypatch):
        _, task = capture_task()
        handler = self._handler(task, monkeypatch)
        monkeypatch.setattr(
            post_mod, "RedisQueue", lambda name: endless_queue()
        )
        refuse(monkeypatch, post_mod)

        assert (
            DownloadPostProcess.refresh_playlist(handler) is False
        ), "must report the stop"

    @staticmethod
    def _run_handler(ran, refresh=True, stopped=False):
        """a post process with every step of run recorded as it goes"""
        return SimpleNamespace(
            VIDEO_QUEUE="v",
            task=SimpleNamespace(is_stopped=lambda: stopped),
            auto_delete_all=lambda: ran.append("auto_delete_all"),
            auto_delete_overwrites=lambda: ran.append("overwrites"),
            refresh_playlist=lambda: ran.append("refresh") or refresh,
            _add_video_playlists=lambda: ran.append("quick sync"),
            match_videos=lambda: ran.append("match"),
            embed_metadata=lambda: ran.append("embed"),
        )

    @staticmethod
    def _run(handler, ran):
        """drive run() with the redis and comment queues recorded"""
        comment_list = SimpleNamespace(
            add=lambda video_ids: ran.append("queue comments"),
            index=lambda: ran.append("comments") or True,
        )
        with mock.patch.object(post_mod, "RedisQueue") as queue:
            queue.return_value = SimpleNamespace(
                clear=lambda: ran.append("clear"),
                get_all=lambda: ["abc"],
            )
            with mock.patch.object(
                post_mod, "CommentList", lambda task: comment_list
            ):
                DownloadPostProcess.run(handler)

    def test_run_does_not_go_to_youtube_after_a_refusal(self):
        """the stop was swallowed here: refresh_playlist broke out of a
        wait that had been cut short and the comment index went straight
        to youtube with no pacing, which is what the wait exists to stop
        """
        ran = []
        self._run(self._run_handler(ran, refresh=False), ran)

        assert "comments" not in ran, "youtube step must be skipped"
        # the local ones still run, so downloaded work is fully filed
        assert "match" in ran and "embed" in ran

    def test_run_queues_comments_even_after_a_refusal(self):
        """queueing is a redis write, not a youtube request

        Skipping it along with the index lost the comments for good:
        the clear at the end of run is the last thing holding those
        video ids, and the comment queue is what carries them into the
        next run.
        """
        ran = []
        self._run(self._run_handler(ran, refresh=False), ran)

        assert "queue comments" in ran
        assert ran.index("queue comments") < ran.index("clear")

    def test_run_skips_the_youtube_steps_when_already_stopped(self):
        """run_queue calls this even when a stop broke its own loop

        Everything up to refresh_playlist's return reaches youtube too -
        auto delete re-extracts each video it ignores - so the check has
        to be up front, not only on that return.
        """
        ran = []
        self._run(self._run_handler(ran, stopped=True), ran)

        assert "auto_delete_all" not in ran
        assert "refresh" not in ran
        assert "comments" not in ran
        assert "queue comments" in ran
        assert "match" in ran and "embed" in ran

    def test_a_stopped_run_still_queues_the_quick_sync(self):
        """_add_video_playlists hangs off refresh_playlist, which a stop
        skips whole - so run has to do it itself or the ids are cleared
        below and those playlists never learn what was downloaded"""
        ran = []
        self._run(self._run_handler(ran, stopped=True), ran)

        assert "quick sync" in ran
        assert ran.index("quick sync") < ran.index("match")

    def test_the_normal_path_leaves_the_quick_sync_to_refresh(self):
        """where it has to run before the full refresh queue is drained,
        so its must_not still excludes what is about to be refreshed"""
        ran = []
        self._run(self._run_handler(ran), ran)

        assert "quick sync" not in ran

    def test_run_does_everything_when_nothing_stops_it(self):
        ran = []
        self._run(self._run_handler(ran), ran)

        assert "comments" in ran
        assert "auto_delete_all" in ran and "refresh" in ran

    def test_countdown_goes_under_the_counter(self, monkeypatch):
        sent, task = capture_task()
        handler = self._handler(task, monkeypatch, length=3)
        seen = []
        record(monkeypatch, post_mod, seen)

        DownloadPostProcess.refresh_playlist(handler)

        assert seen == ["next playlist"]
        assert sent[-1] == [
            "Post Processing Playlists for: Some Channel",
            "Some Playlist [1/1]",
            "Waiting 8s before next playlist",
        ]

    def test_pacing_happens_without_a_task(self, monkeypatch):
        """the wait used to sit behind an early continue for this case

        No task means nowhere to narrate to, so the label is empty - but
        the wait itself still has to happen. Skipping it left a
        scheduled refresh hitting youtube with no pacing at all.
        """
        handler = self._handler(None, monkeypatch, length=3)
        seen = []
        record(monkeypatch, post_mod, seen)

        DownloadPostProcess.refresh_playlist(handler)

        assert seen == [""], "an untasked refresh still paces"


class TestPostProcessChannelScan:
    """download/src/yt_dlp_handler.py DownloadPostProcess

    _add_channel_playlists asks youtube for the playlists of every
    channel with index_playlists set, and used to do it with neither
    pacing nor a stop check - so it was the first thing a stopped
    download run went on to hammer youtube with.
    """

    @staticmethod
    def _queue(length=1, endless=False):
        """a channel queue that also takes the playlists back"""
        queue = endless_queue() if endless else queue_of_one(length)
        queue.add_list = lambda to_add: None

        return queue

    def _handler(self, task, monkeypatch, length=1, indexes=True, built=None):
        monkeypatch.setattr(
            post_mod, "RedisQueue", lambda name: self._queue(length)
        )
        # no default on task: this is the loop the bot block wait had to
        # become interruptible in, so a construction that forgets to
        # hand the task over has to fail here rather than pass quietly
        monkeypatch.setattr(
            post_mod,
            "YoutubeChannel",
            lambda channel_id, task: (
                built.append(task) if built is not None else None
            )
            or SimpleNamespace(
                get_from_es=lambda: None,
                json_data={"channel_name": "Some Channel"},
                get_overwrites=lambda: {"index_playlists": indexes},
                get_all_playlists=lambda: None,
                all_playlists=[("PL1", "One")],
            ),
        )
        handler = SimpleNamespace(
            CHANNEL_QUEUE="c", PLAYLIST_QUEUE="q", config=CONFIG, task=task
        )
        handler._notify_channel_scan = (
            lambda *a, **kw: DownloadPostProcess._notify_channel_scan(
                handler, *a, **kw
            )
        )
        handler._wait_for_next_channel = (
            lambda *a: DownloadPostProcess._wait_for_next_channel(handler, *a)
        )

        return handler

    def test_a_stop_leaves_the_loop(self, monkeypatch):
        _, task = capture_task()
        handler = self._handler(task, monkeypatch)
        monkeypatch.setattr(
            post_mod, "RedisQueue", lambda name: self._queue(endless=True)
        )
        refuse(monkeypatch, post_mod)

        assert (
            DownloadPostProcess._add_channel_playlists(handler) is False
        ), "must report the stop"

    def test_a_stop_request_ends_it_before_the_next_channel(self, monkeypatch):
        """the check sits before get_next, so the channel stays queued"""
        _, task = capture_task()
        task.is_stopped = lambda: True
        popped = []
        queue = self._queue(endless=True)
        inner = queue.get_next
        queue.get_next = lambda: popped.append(1) or inner()
        handler = self._handler(task, monkeypatch)
        monkeypatch.setattr(post_mod, "RedisQueue", lambda name: queue)

        assert DownloadPostProcess._add_channel_playlists(handler) is False
        assert not popped, "a popped channel is off the queue for good"

    def test_countdown_goes_under_the_counter(self, monkeypatch):
        sent, task = capture_task()
        handler = self._handler(task, monkeypatch, length=3)
        seen = []
        record(monkeypatch, post_mod, seen)

        DownloadPostProcess._add_channel_playlists(handler)

        assert seen == ["next channel"]
        assert sent[-1] == [
            "Post Processing Playlists",
            "Scanning channel 1/1 for playlists",
            "Waiting 8s before next channel",
        ]

    def test_the_channel_carries_the_task(self, monkeypatch):
        """get_all_playlists reaches youtube, so its bot block wait has
        to be able to see a stop"""
        _, task = capture_task()
        built: list = []
        handler = self._handler(task, monkeypatch, built=built)
        record(monkeypatch, post_mod, [])

        DownloadPostProcess._add_channel_playlists(handler)

        assert built == [task]

    def test_no_wait_when_nothing_went_to_youtube(self, monkeypatch):
        """a channel without index_playlists never leaves elasticsearch"""
        _, task = capture_task()
        handler = self._handler(task, monkeypatch, indexes=False)
        seen = []
        record(monkeypatch, post_mod, seen)

        assert DownloadPostProcess._add_channel_playlists(handler) is True
        assert seen == [], "nothing to pace"


class TestFailedRequestsStillPace:
    """a spent youtube request owes the wait whether or not it worked

    All three of these skipped it on failure, which inverts the point of
    the setting: a run where requests are failing is a bot block, and a
    bot block is when pacing matters most.
    """

    def test_a_failed_extraction_paces(self, monkeypatch):
        """queue.py PendingList._parse_video"""
        _, task = capture_task()
        monkeypatch.setattr(
            queue_mod,
            "YoutubeVideo",
            lambda youtube_id: SimpleNamespace(
                get_from_youtube=lambda: None,
                youtube_meta=None,
                error="no metadata",
            ),
        )
        handler = SimpleNamespace(
            config=CONFIG,
            task=task,
            videos_failed_count=0,
            extraction_failed=False,
        )
        handler._pace = lambda notify: PendingList._pace(handler, notify)
        handler._extract_video = lambda *a: PendingList._extract_video(
            handler, *a
        )
        seen = []
        record(monkeypatch, queue_mod, seen)

        assert PendingList._parse_video(handler, "abc", None) is None
        assert seen == ["next video"], "the spent request still paces"

    def test_a_failed_playlist_import_paces(self, monkeypatch):
        """yt_dlp_handler.py DownloadPostProcess.refresh_playlist"""
        _, task = capture_task()
        handler = TestPostProcessPlaylists._handler(task, monkeypatch)
        monkeypatch.setattr(
            post_mod,
            "YoutubePlaylist",
            lambda playlist_id: SimpleNamespace(
                update_playlist=lambda skip_on_empty=False: True,
                json_data=None,
            ),
        )
        seen = []
        record(monkeypatch, post_mod, seen)

        assert DownloadPostProcess.refresh_playlist(handler) is True
        assert seen == [""], "update_playlist is what failed, so it paces"

    def test_a_failed_download_paces(self, monkeypatch):
        """yt_dlp_handler.py VideoDownloader.run_queue"""
        _, task = capture_task()
        pending = [
            {"youtube_id": i, "channel_id": "c", "vid_type": "videos"}
            for i in ("a", "b")
        ]
        items = iter(pending + [False])
        handler = SimpleNamespace(
            config=CONFIG,
            task=task,
            _get_next=lambda auto_only: next(items),
            _reset_auto=lambda: None,
            _dl_single_vid=lambda youtube_id, channel_id: False,
        )
        handler._notify = lambda *a, **kw: VideoDownloader._notify(
            handler, *a, **kw
        )
        monkeypatch.setattr(
            post_mod,
            "DownloadPostProcess",
            lambda task: SimpleNamespace(run=lambda: None),
        )
        seen = []
        record(monkeypatch, post_mod, seen)

        assert VideoDownloader.run_queue(handler) == (0, 2)
        assert seen == ["download"], "the second attempt paid the wait"
