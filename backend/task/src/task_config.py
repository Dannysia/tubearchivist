"""
Functionality:
- Static Task config values
- Type definitions
- separate to avoid circular imports
"""

from typing import NotRequired, TypedDict


class TaskItemConfig(TypedDict):
    """describes a task item config"""

    title: str
    group: str
    api_start: bool
    api_stop: bool
    # optional, defaults to api_stop. Only set it to split the two:
    # stop asks the loop to finish the item it is on and leave, kill
    # terminates the worker wherever it happens to be.
    api_kill: NotRequired[bool]


UPDATE_SUBSCRIBED: TaskItemConfig = {
    "title": "Rescan your Subscriptions",
    "group": "download:scan",
    "api_start": True,
    "api_stop": True,
}

DOWNLOAD_PENDING: TaskItemConfig = {
    "title": "Downloading",
    "group": "download:run",
    "api_start": True,
    "api_stop": True,
}

EXTRACT_DOWNLOAD: TaskItemConfig = {
    "title": "Add to extraction queue",
    "group": "download:add",
    "api_start": False,
    "api_stop": True,
}

PROCESS_EXTRACTION_QUEUE: TaskItemConfig = {
    "title": "Extracting queue",
    "group": "download:extract",
    "api_start": False,
    "api_stop": True,
}

CHECK_REINDEX: TaskItemConfig = {
    "title": "Reindex Documents",
    "group": "reindex:run",
    "api_start": False,
    # stoppable: the run only checks between items, after the current
    # one is fully indexed and cleared, so a stop never leaves a half
    # written document. Whatever is still queued stays queued in redis
    # and is picked up first on the next scheduled run.
    "api_stop": True,
    # but not killable. None of the above holds for a terminate: the id
    # has already been popped off the queue, and reindex_single_video
    # deletes the old subtitle files before it writes the new document,
    # so a kill in that window loses the queue entry and leaves ES
    # advertising subtitles that are gone from disk.
    "api_kill": False,
}

MANUAL_IMPORT: TaskItemConfig = {
    "title": "Manual video import",
    "group": "setting:import",
    "api_start": False,
    # process_videos checks between videos, and paced imports are long
    # enough that being unable to stop one is a real problem
    "api_stop": True,
}

RUN_BACKUP: TaskItemConfig = {
    "title": "Index Backup",
    "group": "setting:backup",
    "api_start": True,
    "api_stop": False,
}

RESTORE_BACKUP: TaskItemConfig = {
    "title": "Restore Backup",
    "group": "setting:restore",
    "api_start": False,
    "api_stop": False,
}

RESCAN_FILESYSTEM: TaskItemConfig = {
    "title": "Rescan your Filesystem",
    "group": "setting:filesystemscan",
    "api_start": False,
    "api_stop": False,
}

THUMBNAIL_CHECK: TaskItemConfig = {
    "title": "Check your Thumbnails",
    "group": "setting:thumbnailcheck",
    "api_start": True,
    "api_stop": False,
}

RESYNC_METADATA: TaskItemConfig = {
    "title": "Sync Metadata to Media Files",
    "group": "setting:thumbnailsync",
    "api_start": True,
    "api_stop": False,
}

INDEX_PLAYLISTS: TaskItemConfig = {
    "title": "Index Channel Playlist",
    "group": "channel:indexplaylist",
    "api_start": False,
    "api_stop": False,
}

DELETE_CHANNEL_VIDEOS: TaskItemConfig = {
    "title": "Delete Channel Videos",
    "group": "channel:deletevideos",
    "api_start": False,
    # deleting a few thousand shorts is one es round trip per video, so
    # long enough that being unable to stop it is a real problem
    "api_stop": True,
}

DOWNSCALE_VIDEO: TaskItemConfig = {
    "title": "Downscale Video",
    "group": "downscale:run",
    "api_start": False,
    "api_stop": True,
}

SUBSCRIBE_TO: TaskItemConfig = {
    "title": "Add Subscription",
    "group": "subscription:add",
    "api_start": False,
    "api_stop": False,
}

VERSION_CHECK: TaskItemConfig = {
    "title": "Look for new Version",
    "group": "",
    "api_start": False,
    "api_stop": False,
}

DOWNSCALE_REAP_LEASES: TaskItemConfig = {
    "title": "Reap Stale Downscale Leases",
    "group": "",
    "api_start": False,
    "api_stop": False,
}

LOG_CLEANUP: TaskItemConfig = {
    "title": "Prune Log Entries",
    "group": "",
    "api_start": False,
    "api_stop": False,
}

TASK_CONFIG: dict[str, TaskItemConfig] = {
    "update_subscribed": UPDATE_SUBSCRIBED,
    "download_pending": DOWNLOAD_PENDING,
    "extract_download": EXTRACT_DOWNLOAD,
    "process_extraction_queue": PROCESS_EXTRACTION_QUEUE,
    "check_reindex": CHECK_REINDEX,
    "manual_import": MANUAL_IMPORT,
    "run_backup": RUN_BACKUP,
    "restore_backup": RESTORE_BACKUP,
    "rescan_filesystem": RESCAN_FILESYSTEM,
    "thumbnail_check": THUMBNAIL_CHECK,
    "resync_metadata": RESYNC_METADATA,
    "index_playlists": INDEX_PLAYLISTS,
    "delete_channel_videos": DELETE_CHANNEL_VIDEOS,
    "subscribe_to": SUBSCRIBE_TO,
    "version_check": VERSION_CHECK,
    "downscale_video": DOWNSCALE_VIDEO,
    "downscale_reap_leases": DOWNSCALE_REAP_LEASES,
    "log_cleanup": LOG_CLEANUP,
}


def get_task_config(task_name: str) -> TaskItemConfig | dict:
    """the config for a task, empty when nothing registered one

    A task with no entry here is a bug rather than a state to design
    around, but it used to be a bug that took out the celery callbacks:
    after_return and _build_message both ran a bare
    TASK_CONFIG.get(name).get(...), so a task the dict had never heard
    of raised inside the callback and reported the run as failed.

    The log writer and the log page's task filter were already written
    for an entry that is missing, which they could never actually see
    while the callbacks raised first. Reads go through here so they can.
    """
    return TASK_CONFIG.get(task_name) or {}
