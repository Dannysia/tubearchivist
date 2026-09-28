"""task model"""

from django.db import models
from django_celery_beat.models import PeriodicTask


class CustomPeriodicTask(PeriodicTask):
    """add custom metadata to task"""

    task_config = models.JSONField(default=dict)

    @property
    def schedule_parsed(self):
        """a count in its interval unit, "legacy", or "" for none"""
        if self.interval_id:
            return str(int(self.interval.every))

        if self.crontab_id:
            return "legacy"

        return ""

    @property
    def human_readable(self):
        if self.interval_id:
            every = int(self.interval.every)
            unit = (
                self.interval.period
                if every != 1
                else self.interval.period.rstrip("s")
            )
            return f"every {every} {unit}"

        if self.crontab_id:
            return (
                f"{self.crontab.human_readable} "
                + "(legacy schedule, re-save to switch to hours)"
            )

        return ""
