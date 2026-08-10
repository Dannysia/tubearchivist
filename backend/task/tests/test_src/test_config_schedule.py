"""test schedule parsing"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from django_celery_beat.models import IntervalSchedule
from task.src.config_schedule import ScheduleBuilder, ScheduleValidator

VALID_SCHEDULES = ["1", "24", "168", 1, 24, "auto", None, "", " 24 "]


@pytest.mark.parametrize("valid_value", VALID_SCHEDULES)
def test_valid_schedule(valid_value):
    """accept whole numbers, 'auto', and empty/None, regardless of unit"""
    validator = ScheduleValidator()
    validator.validate_schedule(valid_value)


INVALID_SCHEDULES = [
    "0",
    "-1",
    "1.5",
    "24h",
    "not a number",
]


@pytest.mark.parametrize("invalid_value", INVALID_SCHEDULES)
def test_invalid_schedule(invalid_value):
    """raise error on non-whole-number or sub-1 schedules"""
    validator = ScheduleValidator()
    with pytest.raises(ValueError):
        validator.validate_schedule(invalid_value)


def test_config_rejects_unknown_key():
    """raise error on unknown config key for a task that does take config"""
    validator = ScheduleValidator()
    with pytest.raises(ValueError, match="invalid config key"):
        validator.validate_config("check_reindex", {"nonexistent": 1})


def test_config_rejects_task_without_config():
    """raise error when a task that doesn't take config gets any"""
    validator = ScheduleValidator()
    with pytest.raises(ValueError, match="doesn't take config"):
        validator.validate_config("download_pending", {"days": 90})


def test_config_accepts_known_key():
    """accept a valid config key for a task that takes config"""
    validator = ScheduleValidator()
    validator.validate_config("check_reindex", {"days": 90})


def test_update_subscribed_uses_minutes():
    """the subscription ticker is scheduled in minutes, not hours"""
    assert (
        ScheduleBuilder.UNITS["update_subscribed"] == IntervalSchedule.MINUTES
    )


def test_downscale_reap_leases_uses_minutes():
    """
    the lease reaper runs every minute - a remote worker's job would
    otherwise hang in status=running for up to an hour past its 60s
    lease before anything noticed the worker died
    """
    assert (
        ScheduleBuilder.UNITS["downscale_reap_leases"]
        == IntervalSchedule.MINUTES
    )


MINUTE_SCHEDULED_TASKS = {"update_subscribed", "downscale_reap_leases"}


def test_other_tasks_default_to_hours():
    """every other task falls back to the hourly interval unit"""
    for task_name in ScheduleBuilder.SCHEDULES:
        if task_name in MINUTE_SCHEDULED_TASKS:
            continue
        assert (
            ScheduleBuilder.UNITS.get(task_name, IntervalSchedule.HOURS)
            == IntervalSchedule.HOURS
        )
