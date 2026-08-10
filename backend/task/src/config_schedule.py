"""
Functionality:
- Handle scheduler config update
"""

from datetime import datetime

from django.utils import dateformat
from django_celery_beat.models import IntervalSchedule
from task.models import CustomPeriodicTask
from task.src.task_config import TASK_CONFIG


class ScheduleBuilder:
    """build schedule dicts for beat"""

    SCHEDULES = {
        "update_subscribed": 5,
        "download_pending": 24,
        "check_reindex": 24,
        "thumbnail_check": 24,
        "run_backup": 168,
        "version_check": 24,
        "downscale_reap_leases": 1,
    }
    # tasks not listed here default to hourly intervals. update_subscribed
    # is a lightweight ticker that only checks which subscriptions are due,
    # so it's safe to run much more frequently than a full rescan.
    # downscale_reap_leases is a lease reaper - a remote worker's job
    # would otherwise hang in status=running for up to an hour after its
    # worker dies, well past the 60s lease it's supposed to hold.
    UNITS = {
        "update_subscribed": IntervalSchedule.MINUTES,
        "downscale_reap_leases": IntervalSchedule.MINUTES,
    }
    MSG = "message:setting"

    def update_schedule(
        self, task_name: str, schedule: str, schedule_conf: dict | None
    ) -> CustomPeriodicTask:
        """update schedule"""
        if schedule == "auto":
            schedule = self.SCHEDULES[task_name]

        task = self.get_set_task(task_name, schedule)

        if schedule_conf:
            for key, value in schedule_conf.items():
                self.set_config(task_name, key, value)

        return task

    def get_set_task(self, task_name, schedule=False):
        """get task"""
        try:
            task = CustomPeriodicTask.objects.get(name=task_name)
        except CustomPeriodicTask.DoesNotExist:
            description = TASK_CONFIG[task_name].get("title")
            task = CustomPeriodicTask(
                name=task_name,
                task=task_name,
                description=description,
            )

        if schedule:
            unit = self.UNITS.get(task_name, IntervalSchedule.HOURS)
            task.interval = self.get_set_interval(int(schedule), unit)
            task.crontab = None
            task.last_run_at = dateformat.make_aware(datetime.now())
            task.save()

        return task

    @staticmethod
    def get_set_interval(
        every: int, period: str = IntervalSchedule.HOURS
    ) -> IntervalSchedule:
        """needs to be validated before"""
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=every, period=period
        )

        return interval

    def set_config(
        self, task_name: str, key: str, value
    ) -> CustomPeriodicTask:
        """set task_config, validate before"""
        task = CustomPeriodicTask.objects.get(name=task_name)
        task.task_config.update({key: value})
        task.save()

        return task


class ScheduleValidator:
    """validate schedule input"""

    CONFIG = {
        "check_reindex": ["days"],
        "run_backup": ["rotate"],
    }

    @staticmethod
    def validate_schedule(schedule) -> None:
        """expect a whole number in the task's unit, or the 'auto' sentinel"""
        if not schedule or schedule == "auto":
            return

        try:
            schedule_int = int(schedule)
        except (TypeError, ValueError) as err:
            raise ValueError("schedule must be a whole number") from err

        if schedule_int < 1:
            raise ValueError("schedule must be at least 1")

    def validate_config(self, task_name: str, schedule_config: dict):
        """validate config for given task"""
        if not schedule_config:
            return

        config_keys = self.CONFIG.get(task_name)
        if not config_keys:
            raise ValueError(f"task '{task_name}' doesn't take config")

        for key in schedule_config:
            if key not in config_keys:
                raise ValueError(f"invalid config key for task '{task_name}'")
