"""test how videos an entry could not extract are reported"""

from types import SimpleNamespace

from download.src.queue import PendingList


def test_failed_videos_of_an_entry_are_logged(capsys):
    handler = SimpleNamespace(videos_attempted=13, videos_failed_count=5)

    PendingList._log_video_failures(handler, 10, 2)

    assert "3 of 3 videos could not be extracted" in capsys.readouterr().out


def test_nothing_failed_logs_nothing(capsys):
    handler = SimpleNamespace(videos_attempted=4, videos_failed_count=0)

    PendingList._log_video_failures(handler, 0, 0)

    assert capsys.readouterr().out == ""
