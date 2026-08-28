"""test what happens at the point youtube calls a request a bot

the rotate is a side effect on the way past. the abort that was already
happening has to survive it, whatever the rotate does.
"""

from types import SimpleNamespace

import pytest
from download.src import yt_dlp_base


def fake_wrap(config=None):
    """enough of a YtWrap for the unbound method"""
    return SimpleNamespace(
        config=config if config is not None else {"downloads": {}},
        task=None,
        BOT_ERROR_LOG=yt_dlp_base.YtWrap.BOT_ERROR_LOG,
    )


@pytest.fixture
def no_sleep(monkeypatch):
    """the real one waits out a randomised interval"""
    monkeypatch.setattr(
        yt_dlp_base, "countdown_sleep", lambda config, task: True
    )


class TestOnBotBlock:
    """the shared branch both download and extract now route through"""

    def test_rotates_then_aborts(self, monkeypatch, no_sleep):
        seen = []
        monkeypatch.setattr(
            yt_dlp_base,
            "rotate_on_bot_block",
            lambda config: seen.append(config) or "rotated somewhere",
        )

        wrap = fake_wrap({"downloads": {"auto_rotate_exit_node": True}})
        with pytest.raises(ConnectionError, match=wrap.BOT_ERROR_LOG):
            yt_dlp_base.YtWrap._on_bot_block(wrap, ValueError("not a bot"))

        assert seen == [{"downloads": {"auto_rotate_exit_node": True}}]

    def test_the_wait_can_see_a_stop_request(self, monkeypatch):
        """a bot block is the moment a user goes and hits stop

        The wait runs up to 1.5x the interval and used to be a plain
        sleep, so the stop landed whenever it happened to finish. The
        refusal changes nothing here - this aborts either way - but the
        poll behind it is the point.
        """
        seen = []
        monkeypatch.setattr(
            yt_dlp_base, "rotate_on_bot_block", lambda config: None
        )
        monkeypatch.setattr(
            yt_dlp_base,
            "countdown_sleep",
            lambda config, task: seen.append(task) or False,
        )
        wrap = fake_wrap()
        wrap.task = "the running task"

        with pytest.raises(ConnectionError, match="bot detection"):
            yt_dlp_base.YtWrap._on_bot_block(wrap, ValueError("nope"))

        assert seen == ["the running task"]

    def test_aborts_the_same_when_rotation_is_off(self, monkeypatch, no_sleep):
        """the silent path, which is every install without tailscale"""
        monkeypatch.setattr(
            yt_dlp_base, "rotate_on_bot_block", lambda config: None
        )

        with pytest.raises(ConnectionError, match="bot detection"):
            yt_dlp_base.YtWrap._on_bot_block(fake_wrap(), ValueError("nope"))

    def test_keeps_the_original_error_as_the_cause(
        self, monkeypatch, no_sleep
    ):
        """so the yt-dlp message is not lost behind the rotate"""
        monkeypatch.setattr(
            yt_dlp_base, "rotate_on_bot_block", lambda config: "rotated"
        )
        original = ValueError("Sign in to confirm you're not a bot")

        with pytest.raises(ConnectionError) as caught:
            yt_dlp_base.YtWrap._on_bot_block(fake_wrap(), original)

        assert caught.value.__cause__ is original


class TestBotMessages:
    """the trigger itself, which this feature now hangs off"""

    def test_the_real_youtube_wording_is_matched(self):
        message = (
            "ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you're not "
            "a bot. Use --cookies-from-browser or --cookies for the "
            "authentication."
        )
        assert any(m in message for m in yt_dlp_base.YtWrap.BOT_MESSAGES)

    def test_an_ordinary_failure_is_not_a_bot_block(self):
        """rotating on every download error would burn the budget on
        videos that are simply gone"""
        message = "ERROR: [youtube] abc: Video unavailable"
        assert not any(m in message for m in yt_dlp_base.YtWrap.BOT_MESSAGES)
