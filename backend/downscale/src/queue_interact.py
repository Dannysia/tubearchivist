"""interact with items in the downscale review queue"""

import os
from datetime import datetime

from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap, IndexPaginate
from common.src.queue_interact import BaseQueueInteract


class DownscaleInteract(BaseQueueInteract):
    """interact with a single item in the downscale review queue"""

    INDEX_NAME = "ta_downscale"

    def create(self, doc: dict) -> str:
        """create a new downscale job doc, return its id. Deterministic
        (keyed on youtube_id) rather than random, so a racing duplicate
        submission for the same video overwrites the same document
        instead of creating a sibling - see docs/downscale-dedup/README.md
        """
        doc_id = doc["youtube_id"]
        path = f"ta_downscale/_doc/{doc_id}"
        ElasticWrap(path).put(doc, refresh=True)
        self.doc_id = doc_id
        return doc_id

    @staticmethod
    def build_queued_doc(
        youtube_id: str,
        video_json_data: dict,
        current_height: int,
        target_height: int,
        task_id: str = "",
    ) -> dict:
        """build a new downscale job doc in status=queued"""
        now = int(datetime.now().timestamp())
        tmp_path = os.path.join(
            EnvironmentSettings.CACHE_DIR,
            "downscale",
            f"{youtube_id}_{target_height}p.mp4",
        )
        return {
            "youtube_id": youtube_id,
            "channel_id": video_json_data["channel"]["channel_id"],
            "channel_name": video_json_data["channel"]["channel_name"],
            "title": video_json_data["title"],
            "vid_thumb_url": video_json_data.get("vid_thumb_url"),
            "media_url": (
                f"{EnvironmentSettings().get_media_root()}/"
                f'{video_json_data["media_url"]}'
            ),
            "status": "queued",
            "current_height": current_height,
            "target_height": target_height,
            "original_size": video_json_data.get("media_size") or 0,
            "new_size": 0,
            "tmp_file_path": tmp_path,
            "task_id": task_id,
            "worker": "",
            "last_heartbeat": 0,
            "progress": 0.0,
            "stop_requested": False,
            "ffmpeg_args": "",
            "timestamp": now,
            "updated": now,
        }

    @staticmethod
    def get_interrupted() -> list[dict]:
        """
        return all local downscale jobs left in status=queued or
        status=running. Only called from ta_startup, before the celery
        worker for this container has been started, so a job in either
        of those states at that point can only be a leftover from a
        hard restart, never one actually in progress. Remote-held jobs
        (worker != "") are excluded - they survive a TA restart just
        fine, and the lease reaper is what cleans those up if their
        worker really is gone. Paginated in batches of 1000 rather than
        a single capped query, since requeue_interrupted()'s bulk reset
        of the same backlog isn't capped and a large enough restart
        backlog could otherwise silently drop jobs past the first 1000
        from the tmp-file cleanup and the reported count.
        """
        data = {
            "query": {
                "bool": {
                    "must": [
                        {"terms": {"status": ["queued", "running"]}},
                        {"term": {"worker": {"value": ""}}},
                    ]
                }
            }
        }
        hits = IndexPaginate(
            "ta_downscale", data, size=1000, keep_source=True
        ).get_results()
        return [{"id": hit["_id"], **hit["_source"]} for hit in hits]

    @staticmethod
    def get_all_tmp_filenames() -> set[str]:
        """
        basenames of tmp_file_path for every job still in the queue,
        e.g. to protect pending_review output from a cache sweep
        """
        data = {
            "query": {"match_all": {}},
            "size": 1000,
            "_source": ["tmp_file_path"],
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        hits = response["hits"]["hits"]
        return {
            os.path.basename(hit["_source"]["tmp_file_path"])
            for hit in hits
            if hit["_source"].get("tmp_file_path")
        }

    @staticmethod
    def get_next_queued(limit: int | None) -> list[dict]:
        """
        oldest still-queued, not-yet-dispatched jobs, oldest first, up to
        limit. Pass None for unlimited concurrency, capped the same way
        get_interrupted() caps "get everything" queries.

        Also excludes anything with a task_id already set - a job stays
        status=queued from the moment it's dispatched until its task
        actually reaches _reserve_slot() and flips it to running, so
        status=queued alone can't tell "never dispatched" apart from
        "dispatched a moment ago, task hasn't started yet". Without this,
        two dispatch_pending_downscales() calls close enough together
        (e.g. two jobs finishing within the same second) could both pick
        the same job and start two celery tasks for one doc.
        """
        size = limit if limit is not None else 1000
        if size <= 0:
            return []

        data = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"status": {"value": "queued"}}},
                        {"term": {"task_id": {"value": ""}}},
                    ]
                }
            },
            "sort": [{"timestamp": {"order": "asc"}}],
            "size": size,
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        hits = response["hits"]["hits"]
        return [{"id": hit["_id"], **hit["_source"]} for hit in hits]

    @staticmethod
    def count_running() -> int:
        """
        count how many downscale jobs are currently running locally.
        Remote jobs (worker != "") are excluded - downscale_max_concurrent
        exists to protect the TA host's own CPU and has nothing to say
        about a remote worker's hardware.
        """
        data = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"status": {"value": "running"}}},
                        {"term": {"worker": {"value": ""}}},
                    ]
                }
            },
            "size": 0,
            "track_total_hits": True,
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        return response["hits"]["total"]["value"]

    def requeue_interrupted(self) -> None:
        """
        bulk-reset every local job left in status=queued/running (e.g.
        by a hard restart) back to status=queued with no task_id, in a
        single ES update_by_query call rather than one round-trip per
        job - the startup auto-resume sweep can be resetting hundreds of
        jobs at once. Remote-held jobs (worker != "") are left alone.
        """
        now = int(datetime.now().timestamp())
        must_list = [
            {"terms": {"status": ["queued", "running"]}},
            {"term": {"worker": {"value": ""}}},
        ]
        script_source = (
            "ctx._source.status = 'queued';"
            "ctx._source.message = null;"
            "ctx._source.task_id = '';"
            f"ctx._source.updated = {now};"
        )
        self._update_by_query(must_list, [], script_source)

    @staticmethod
    def get_active_for_video(
        youtube_id: str, exclude_id: str | None = None
    ) -> dict | None:
        """
        return a queued, running, or pending_review job for this video,
        if any. pass exclude_id to ignore a job's own doc when checking
        for other active jobs on the same video
        """
        must: list[dict] = [
            {"term": {"youtube_id": {"value": youtube_id}}},
            {"terms": {"status": ["queued", "running", "pending_review"]}},
        ]
        must_not: list[dict] = []
        if exclude_id:
            must_not.append({"term": {"_id": {"value": exclude_id}}})

        data = {
            "query": {"bool": {"must": must, "must_not": must_not}},
            "size": 1,
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        hits = response["hits"]["hits"]
        if not hits:
            return None

        return {"id": hits[0]["_id"], **hits[0]["_source"]}

    @staticmethod
    def get_stale_leases(stale_before: int) -> list[dict]:
        """
        remote-held (worker != "") running jobs whose last_heartbeat is
        older than stale_before - a crashed or powered-off worker never
        renewed its lease. Callers branch per-job on stop_requested:
        with it set the user already cancelled and the worker just never
        acked, without it the job goes back to the queue. Capped like
        every other "get everything matching" query in this module.
        """
        data = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"status": {"value": "running"}}},
                        # last_heartbeat is mapped date/epoch_second, but
                        # ES reads a bare numeric on a date field as epoch
                        # *millis* - without an explicit format every
                        # epoch-second value looks like Jan 1970 and the
                        # range never matches anything
                        {
                            "range": {
                                "last_heartbeat": {
                                    "lt": stale_before,
                                    "format": "epoch_second",
                                }
                            }
                        },
                    ],
                    "must_not": [{"term": {"worker": {"value": ""}}}],
                }
            },
            "size": 1000,
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        hits = response["hits"]["hits"]
        return [{"id": hit["_id"], **hit["_source"]} for hit in hits]
