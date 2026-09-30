"""test schedule parsing"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from django_celery_beat.models import IntervalSchedule
from task.src.config_schedule import (
    ScheduleBuilder,
    ScheduleValidator,
    orphaned_schedules,
)
from task.src.task_config import TASK_CONFIG

VALID_SCHEDULES = ["1", "24", "168", 1, 24, "auto", None, "", " 24 "]


@pytest.mark.parametrize("valid_value", VALID_SCHEDULES)
def test_valid_schedule(valid_value):
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
    validator = ScheduleValidator()
    with pytest.raises(ValueError):
        validator.validate_schedule(invalid_value)


def test_config_rejects_unknown_key():
    validator = ScheduleValidator()
    with pytest.raises(ValueError, match="invalid config key"):
        validator.validate_config("check_reindex", {"nonexistent": 1})


def test_config_rejects_task_without_config():
    validator = ScheduleValidator()
    with pytest.raises(ValueError, match="doesn't take config"):
        validator.validate_config("download_pending", {"days": 90})


def test_config_accepts_known_key():
    validator = ScheduleValidator()
    validator.validate_config("check_reindex", {"days": 90})


def test_update_subscribed_uses_minutes():
    assert (
        ScheduleBuilder.UNITS["update_subscribed"] == IntervalSchedule.MINUTES
    )


def test_downscale_reap_leases_uses_minutes():
    assert (
        ScheduleBuilder.UNITS["downscale_reap_leases"]
        == IntervalSchedule.MINUTES
    )


MINUTE_SCHEDULED_TASKS = {"update_subscribed", "downscale_reap_leases"}


def test_other_tasks_default_to_hours():
    for task_name in ScheduleBuilder.SCHEDULES:
        if task_name in MINUTE_SCHEDULED_TASKS:
            continue
        assert (
            ScheduleBuilder.UNITS.get(task_name, IntervalSchedule.HOURS)
            == IntervalSchedule.HOURS
        )


class TestOrphanedSchedules:
    def test_nothing_orphaned_when_every_name_is_known(self):
        known = ["download_pending", "log_cleanup"]
        assert orphaned_schedules(known, known) == []

    def test_finds_a_schedule_with_no_task_behind_it(self):
        assert orphaned_schedules(
            ["download_pending", "log_cleanup"], ["download_pending"]
        ) == ["log_cleanup"]

    def test_a_known_task_without_a_schedule_is_not_orphaned(self):
        assert (
            orphaned_schedules(["log_cleanup"], ["log_cleanup", "run_backup"])
            == []
        )

    def test_refuses_to_act_on_an_empty_known_set(self):
        assert (
            orphaned_schedules(["download_pending", "log_cleanup"], []) == []
        )

    def test_result_is_ordered_so_the_startup_output_is_stable(self):
        assert orphaned_schedules(["zeta", "alpha"], ["other"]) == [
            "alpha",
            "zeta",
        ]

    def test_the_real_task_config_orphans_nothing_today(self):
        assert orphaned_schedules(TASK_CONFIG.keys(), TASK_CONFIG) == []


def test_reindex_is_stoppable():
    assert TASK_CONFIG["check_reindex"]["api_stop"] is True


def test_reindex_is_not_killable():
    assert TASK_CONFIG["check_reindex"]["api_kill"] is False


def test_api_kill_defaults_to_api_stop():
    for name, config in TASK_CONFIG.items():
        if name == "check_reindex":
            continue

        assert "api_kill" not in config, f"{name} should not need to opt out"
