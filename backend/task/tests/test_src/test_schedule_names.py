"""test which task names a schedule can be created for"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from task import views
from task.views import ScheduleView


@pytest.fixture
def created(monkeypatch):
    calls = []

    class Builder:
        SCHEDULES = views.ScheduleBuilder.SCHEDULES

        def update_schedule(self, task_name, schedule, config):
            calls.append(task_name)
            return SimpleNamespace()

    monkeypatch.setattr(views, "ScheduleBuilder", Builder)
    monkeypatch.setattr(
        views,
        "CustomPeriodicTaskSerializer",
        lambda task: SimpleNamespace(data={}),
    )
    return calls


@pytest.mark.parametrize("task_name", ["manual_import", "no_such_task"])
def test_an_unschedulable_name_is_refused(created, task_name):
    request = SimpleNamespace(data={"schedule": "auto"})

    response = ScheduleView().post(request, task_name)

    assert response.status_code == 404
    assert created == []


def test_a_schedulable_task_is_scheduled(created):
    request = SimpleNamespace(data={"schedule": "auto"})

    response = ScheduleView().post(request, "update_subscribed")

    assert response.status_code == 200
    assert created == ["update_subscribed"]
