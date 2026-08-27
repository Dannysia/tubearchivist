"""
Functionality:
- Application startup
- Apply migrations
"""

import os
from datetime import datetime
from time import sleep

from appsettings.src.config import AppConfig, ReleaseVersion
from appsettings.src.index_setup import ElasticIndexWrap
from appsettings.src.snapshot import ElasticSnapshot
from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap
from common.src.helper import clear_dl_cache
from common.src.ta_redis import RedisArchivist
from django.core.management.base import BaseCommand, CommandError
from django_celery_beat.models import (
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTasks,
)
from downscale.src.downscale import dispatch_pending_downscales
from downscale.src.queue_interact import DownscaleInteract
from task.models import CustomPeriodicTask
from task.src.config_schedule import ScheduleBuilder
from task.src.task_manager import TaskManager
from task.tasks import version_check

TOPIC = """

#######################
#  Application Start  #
#######################

"""


class Command(BaseCommand):
    """command framework"""

    def handle(self, *args, **options):
        """run all commands"""
        self.stdout.write(TOPIC)
        self._make_folders()
        self._clear_redis_keys()
        self._clear_tasks()
        self._clear_dl_cache()
        self._version_check()
        self._index_setup()
        self._clear_downscale_leftovers()
        self._snapshot_check()
        self._create_default_schedules()
        self._update_schedule_tz()
        self._init_app_config()
        self._set_ta_startup_time()

    def _make_folders(self):
        """make expected cache folders"""
        self.stdout.write("[1] create expected cache folders")
        folders = [
            "backup",
            "channels",
            "download",
            "downscale",
            "import",
            "playlists",
            "videos",
            "ytdlp",
        ]
        cache_dir = EnvironmentSettings.CACHE_DIR
        for folder in folders:
            folder_path = os.path.join(cache_dir, folder)
            os.makedirs(folder_path, exist_ok=True)

        self.stdout.write(self.style.SUCCESS("    ✓ expected folders created"))

    def _clear_redis_keys(self):
        """make sure there are no leftover locks or keys set in redis"""
        self.stdout.write("[2] clear leftover keys in redis")
        all_keys = [
            "dl_queue_id",
            "dl_queue",
            "downloading",
            "manual_import",
            "reindex",
            "rescan",
            "run_backup",
            "startup_check",
            "reindex:ta_video",
            "reindex:ta_channel",
            "reindex:ta_playlist",
        ]

        redis_con = RedisArchivist()
        has_changed = False
        for key in all_keys:
            if redis_con.del_message(key):
                self.stdout.write(
                    self.style.SUCCESS(f"    ✓ cleared key {key}")
                )
                has_changed = True

        if not has_changed:
            self.stdout.write(self.style.SUCCESS("    no keys found"))

    def _clear_tasks(self):
        """clear tasks and messages"""
        self.stdout.write("[3] clear task leftovers")
        TaskManager().fail_pending()
        redis_con = RedisArchivist()
        to_delete = redis_con.list_keys("message:")
        if to_delete:
            for key in to_delete:
                redis_con.del_message(key)

            self.stdout.write(
                self.style.SUCCESS(f"    ✓ cleared {len(to_delete)} messages")
            )

    def _clear_dl_cache(self):
        """clear leftover files from dl cache"""
        self.stdout.write("[4] clear leftover files from dl cache")
        leftover_files = clear_dl_cache(EnvironmentSettings.CACHE_DIR)
        if leftover_files:
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ cleared {leftover_files} files")
            )
        else:
            self.stdout.write(self.style.SUCCESS("    no files found"))

    def _clear_downscale_leftovers(self):
        """
        auto-resume any downscale job left queued or running by a hard
        restart, then clear cache files not spoken for by any job still
        in the queue. The celery worker for this container isn't
        started until after this command finishes, so a job in either
        of those states now can only be a leftover, never one actually
        in progress. Jobs already marked failed are left alone for
        manual review/retry.
        """
        self.stdout.write("[4b] resume interrupted downscale jobs")
        self._backfill_downscale_worker_fields()

        interrupted = DownscaleInteract.get_interrupted()
        for job in interrupted:
            tmp_path = job.get("tmp_file_path")
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

        if interrupted:
            # one query resets every interrupted job's status/task_id at
            # once instead of a per-job ES round-trip - matters once
            # this is resetting hundreds of jobs on startup
            DownscaleInteract().requeue_interrupted()
            # dispatch is just enqueueing to the broker, so it's fine to
            # call before the celery worker itself has started - one
            # pass covers the whole batch rather than once per job
            dispatch_pending_downscales()
            self.stdout.write(
                self.style.SUCCESS(
                    f"    ✓ resumed {len(interrupted)} interrupted job(s)"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("    no interrupted jobs found")
            )

        keep = DownscaleInteract.get_all_tmp_filenames()
        leftover_files = clear_dl_cache(
            EnvironmentSettings.CACHE_DIR, subfolder="downscale", keep=keep
        )
        if leftover_files:
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ cleared {leftover_files} files")
            )
        else:
            self.stdout.write(self.style.SUCCESS("    no files found"))

    def _backfill_downscale_worker_fields(self) -> None:
        """
        add the remote-worker fields (worker/last_heartbeat/progress/
        stop_requested/ffmpeg_args) to any downscale queue doc that
        predates them. get_interrupted()/requeue_interrupted() (called
        right after this) and count_running() all key off worker=="" to
        tell a local job from a remote one, so a doc missing the field
        entirely would be invisible to this very startup sweep and to
        the concurrency counter, with nothing else ever going to notice
        it again (the lease reaper only looks at worker != ""). This has
        to run before that sweep.
        """
        self._run_migration(
            index_name="ta_downscale",
            desc="add remote-worker fields to downscale queue docs",
            query={"bool": {"must_not": [{"exists": {"field": "worker"}}]}},
            script={
                "source": (
                    "ctx._source.worker = '';"
                    "ctx._source.last_heartbeat = 0;"
                    "ctx._source.progress = 0.0;"
                    "ctx._source.stop_requested = false;"
                    "ctx._source.ffmpeg_args = '';"
                ),
                "lang": "painless",
            },
        )

    def _version_check(self):
        """remove new release key if updated now"""
        self.stdout.write("[5] check for first run after update")
        new_version = ReleaseVersion().is_updated()
        if new_version:
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ update to {new_version} completed")
            )
        else:
            self.stdout.write(self.style.SUCCESS("    no new update found"))

        version_task = CustomPeriodicTask.objects.filter(name="version_check")
        if not version_task.exists():
            return

        if not version_task.first().last_run_at:
            self.style.SUCCESS("    ✓ send initial version check task")
            version_check.delay()

    def _index_setup(self):
        """migration: validate index mappings"""
        self.stdout.write("[6] validate index mappings")
        ElasticIndexWrap().setup()

    def _snapshot_check(self):
        """migration setup snapshots"""
        self.stdout.write("[7] setup snapshots")
        ElasticSnapshot().setup()

    def _create_default_schedules(self) -> None:
        """create default schedules for new installations, migrate any
        pre-existing crontab-based auto schedules to the interval format"""
        self.stdout.write("[8] create initial schedules")
        builder = ScheduleBuilder()

        for task_name in (
            "check_reindex",
            "thumbnail_check",
            "version_check",
            "downscale_reap_leases",
            "log_cleanup",
        ):
            existing = CustomPeriodicTask.objects.filter(
                name=task_name
            ).first()
            if existing and existing.interval_id:
                self.stdout.write(
                    self.style.SUCCESS(f"    schedule up to date: {task_name}")
                )
                continue

            task = builder.get_set_task(
                task_name, schedule=builder.SCHEDULES[task_name]
            )
            if task_name == "check_reindex":
                task.task_config.update({"days": 90})
                task.save()

            self.stdout.write(
                self.style.SUCCESS(f"    ✓ schedule set: {task}")
            )

        self._mig_update_subscribed_to_minutes(builder)

        self.stdout.write(
            self.style.SUCCESS("    ✓ all default schedules created")
        )

    def _mig_update_subscribed_to_minutes(
        self, builder: ScheduleBuilder
    ) -> None:
        """migrate a pre-existing update_subscribed schedule from hours to
        the new minutes-based interval, resetting to the default cadence
        since the old number no longer means the same thing"""
        task_name = "update_subscribed"
        existing = CustomPeriodicTask.objects.filter(name=task_name).first()
        if not existing:
            # opt-in schedule, nothing to migrate until the user sets one
            return

        if (
            existing.interval_id
            and existing.interval.period == IntervalSchedule.MINUTES
        ):
            self.stdout.write(
                self.style.SUCCESS(f"    schedule up to date: {task_name}")
            )
            return

        task = builder.get_set_task(
            task_name, schedule=builder.SCHEDULES[task_name]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"    ✓ migrated {task_name} to minutes-based interval: {task}"
            )
        )

    def _update_schedule_tz(self) -> None:
        """update timezone for Schedule instances"""
        self.stdout.write("[9] validate schedules TZ")
        tz = EnvironmentSettings.TZ
        to_update = CrontabSchedule.objects.exclude(timezone=tz)

        if not to_update.exists():
            self.stdout.write(
                self.style.SUCCESS("    all schedules have correct TZ")
            )
            return

        updated = to_update.update(timezone=tz)
        self.stdout.write(
            self.style.SUCCESS(f"    ✓ updated {updated} schedules to {tz}.")
        )
        PeriodicTasks.update_changed()

    def _init_app_config(self) -> None:
        """init default app config to ES"""
        self.stdout.write("[10] Check AppConfig")
        response, status_code = ElasticWrap("ta_config/_doc/appsettings").get()
        if status_code in [200, 201]:
            self.stdout.write(
                self.style.SUCCESS("    skip completed appsettings init")
            )
            updated_defaults = AppConfig().add_new_defaults()
            for new_default in updated_defaults:
                self.stdout.write(
                    self.style.SUCCESS(f"    added new default: {new_default}")
                )

            cleared = AppConfig().clear_old_keys()
            for removed_key in cleared:
                self.stdout.write(
                    self.style.SUCCESS(f"    removed old key: {removed_key}")
                )

            return

        if status_code != 404:
            message = "    🗙 ta_config index lookup failed"
            self.stdout.write(self.style.ERROR(message))
            self.stdout.write(response)
            sleep(60)
            raise CommandError(message)

        handler = AppConfig.__new__(AppConfig)
        _, status_code = handler.sync_defaults()
        self.stdout.write(
            self.style.SUCCESS("    ✓ Created default appsettings.")
        )
        self.stdout.write(
            self.style.SUCCESS(f"      Status code: {status_code}")
        )

    def _set_ta_startup_time(self) -> None:
        """set startup time to trigger frontend refresh, threadsafe"""
        self.stdout.write("[11] Set startup timestamp")
        message = str(int(datetime.now().timestamp() // 10 * 10))
        RedisArchivist().set_message(
            "STARTTIMESTAMP", message=message, save=True
        )
        self.stdout.write(
            self.style.SUCCESS(f"    ✓ set timestamp to {message}.")
        )

    def _run_migration(
        self, index_name: str, desc: str, query: dict, script: dict
    ):
        """run migration"""
        self.stdout.write(f"[MIGRATION] run {desc}")
        path = f"{index_name}/_update_by_query?wait_for_completion=true"
        data = {"query": query, "script": script}
        response, status_code = ElasticWrap(path).post(data)
        if status_code in [200, 201]:
            updated = response.get("updated")
            if updated:
                suc_msg = f"    ✓ updated {updated} docs in {index_name}"
                self.stdout.write(self.style.SUCCESS(suc_msg))

                # ensure index consistency
                ElasticWrap(f"{index_name}/_refresh").post()
            else:
                noop_msg = f"    no items in {index_name} need updating"
                self.stdout.write(self.style.SUCCESS(noop_msg))
            return

        message = f"    🗙 failed to run {desc} on index {index_name}"
        self.stdout.write(self.style.ERROR(message))
        self.stdout.write(response)
        sleep(60)
        raise CommandError(message)
