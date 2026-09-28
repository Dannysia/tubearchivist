from types import SimpleNamespace

from download.src.queue import PendingList


def capture():
    """returns (what reached the task, the task)"""
    captured = []

    def send_progress(message_lines, progress=False):
        captured.append((message_lines, progress))

    return captured, SimpleNamespace(send_progress=send_progress)


class TestPendingListNotify:
    def test_plain_line_while_working(self):
        captured, task = capture()
        PendingList._notify(SimpleNamespace(task=task), 8, 60)

        assert captured == [(["Extracting URL 8/60"], 8 / 60)]

    def test_countdown_goes_under_the_counter(self):
        captured, task = capture()
        PendingList._notify(
            SimpleNamespace(task=task),
            8,
            60,
            waiting="Waiting 12s before next URL",
        )

        message, progress = captured[0]
        assert message == [
            "Extracting URL 8/60",
            "Waiting 12s before next URL",
        ]
        assert progress == 8 / 60
