"""test the channel batch downscale endpoint"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from channel import views
from channel.views import ChannelDownscaleView


class Delay:
    def __init__(self):
        self.calls = []

    def delay(self, *args):
        self.calls.append(args)
        return SimpleNamespace(id="task-1")


def _view(monkeypatch, found=True):
    view = ChannelDownscaleView()

    def get_document(self, channel_id):
        self.response = {"channel_id": channel_id} if found else {}

    monkeypatch.setattr(ChannelDownscaleView, "get_document", get_document)
    task = Delay()
    monkeypatch.setattr(views, "downscale_channel", task)
    return view, task


def test_the_batch_runs_as_a_task(monkeypatch):
    view, task = _view(monkeypatch)

    response = view.post(SimpleNamespace(data={"target_height": 480}), "UC1")

    assert response.status_code == 202
    assert response.data["task_id"] == "task-1"
    assert task.calls == [("UC1", 480, False)]


def test_skip_inactive_reaches_the_task(monkeypatch):
    view, task = _view(monkeypatch)

    view.post(
        SimpleNamespace(data={"target_height": 480, "skip_inactive": True}),
        "UC1",
    )

    assert task.calls == [("UC1", 480, True)]


def test_an_unknown_channel_starts_nothing(monkeypatch):
    view, task = _view(monkeypatch, found=False)

    response = view.post(SimpleNamespace(data={"target_height": 480}), "UC1")

    assert response.status_code == 404
    assert task.calls == []
