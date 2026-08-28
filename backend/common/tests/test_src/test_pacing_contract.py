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
from download.src import yt_dlp_handler as post_mod
from download.src.yt_dlp_handler import DownloadPostProcess
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
            lambda youtube_id, config=None: SimpleNamespace(
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
            lambda youtube_id, config=None: indexed.append(youtube_id)
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
            add_playlists_to_refresh=lambda: None,
        )
        handler._notify_playlist = (
            lambda *a, **kw: DownloadPostProcess._notify_playlist(
                handler, *a, **kw
            )
        )
        handler._wait_for_next_playlist = (
            lambda *a: DownloadPostProcess._wait_for_next_playlist(handler, *a)
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

    def test_run_does_not_go_to_youtube_after_a_refusal(self):
        """the stop was swallowed here: refresh_playlist broke out of a
        wait that had been cut short and get_comments went straight to
        youtube with no pacing, which is what the wait exists to stop"""
        ran = []
        handler = SimpleNamespace(
            VIDEO_QUEUE="v",
            auto_delete_all=lambda: ran.append("auto_delete_all"),
            auto_delete_overwrites=lambda: ran.append("overwrites"),
            refresh_playlist=lambda: ran.append("refresh") or False,
            match_videos=lambda: ran.append("match"),
            get_comments=lambda: ran.append("comments") or True,
            embed_metadata=lambda: ran.append("embed"),
        )

        with mock.patch.object(post_mod, "RedisQueue") as queue:
            queue.return_value = SimpleNamespace(clear=lambda: None)
            DownloadPostProcess.run(handler)

        assert "comments" not in ran, "youtube step must be skipped"
        # the local ones still run, so downloaded work is fully filed
        assert "match" in ran and "embed" in ran

    def test_run_does_everything_when_nothing_stops_it(self):
        ran = []
        handler = SimpleNamespace(
            VIDEO_QUEUE="v",
            auto_delete_all=lambda: ran.append("auto_delete_all"),
            auto_delete_overwrites=lambda: ran.append("overwrites"),
            refresh_playlist=lambda: ran.append("refresh") or True,
            match_videos=lambda: ran.append("match"),
            get_comments=lambda: ran.append("comments") or True,
            embed_metadata=lambda: ran.append("embed"),
        )

        with mock.patch.object(post_mod, "RedisQueue") as queue:
            queue.return_value = SimpleNamespace(clear=lambda: None)
            DownloadPostProcess.run(handler)

        assert "comments" in ran

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
