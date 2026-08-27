"""the progress lines the url extraction loop sends

the loop paces itself between urls. without the countdown underneath,
the url counter sat frozen for the whole interval.
"""

from types import SimpleNamespace

from download.src.queue import PendingList


def capture():
    """capture what reaches the task"""
    captured = []

    def send_progress(message_lines, progress=False):
        captured.append((message_lines, progress))

    return captured, SimpleNamespace(send_progress=send_progress)


class TestPendingListNotify:
    """PendingList._notify"""

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
