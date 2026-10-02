from types import SimpleNamespace


def capture_task():
    """returns (the message lines sent, the task)"""
    sent = []
    task = SimpleNamespace(
        is_stopped=lambda: False,
        send_progress=lambda *a, **kw: sent.append(
            a[0] if a else kw.get("message_lines")
        ),
    )
    return sent, task
