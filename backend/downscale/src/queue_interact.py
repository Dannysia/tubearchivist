"""interact with items in the downscale review queue"""

import os
import uuid
from datetime import datetime

from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap
from common.src.queue_interact import BaseQueueInteract


class DownscaleInteract(BaseQueueInteract):
    """interact with a single item in the downscale review queue"""

    INDEX_NAME = "ta_downscale"

    def create(self, doc: dict) -> str:
        """create a new downscale job doc, return its id"""
        doc_id = uuid.uuid4().hex
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
            "timestamp": now,
            "updated": now,
        }

    @staticmethod
    def get_interrupted() -> list[dict]:
        """
        return all downscale jobs left in status=queued or
        status=running. Only called from ta_startup, before the celery
        worker for this container has been started, so a job in either
        of those states at that point can only be a leftover from a
        hard restart, never one actually in progress.
        """
        data = {
            "query": {"terms": {"status": ["queued", "running"]}},
            "size": 1000,
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        hits = response["hits"]["hits"]
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
        """count how many downscale jobs are currently running"""
        data = {
            "query": {"term": {"status": {"value": "running"}}},
            "size": 0,
            "track_total_hits": True,
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        return response["hits"]["total"]["value"]

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
