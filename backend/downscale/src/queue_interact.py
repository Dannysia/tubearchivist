import os
from datetime import datetime

from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap, IndexPaginate
from common.src.queue_interact import BaseQueueInteract


class DownscaleInteract(BaseQueueInteract):
    INDEX_NAME = "ta_downscale"

    def create(self, doc: dict) -> str:
        """
        the id is keyed on youtube_id rather than random, so a racing
        duplicate submission overwrites the same document instead of
        creating a sibling
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
        only meaningful before this container's celery worker starts: a
        job in either state at that point can only be a leftover from a
        hard restart, never one in progress. Remote-held jobs (worker !=
        "") survive a TA restart and are left to the lease reaper.
        Paginated rather than capped because requeue_interrupted()
        resets the same backlog uncapped, so jobs past the first 1000
        would go missing from the tmp cleanup and the reported count.
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
        # failed is left out on purpose
        data = {
            "query": {
                "terms": {"status": ["queued", "running", "pending_review"]}
            },
            "_source": ["tmp_file_path"],
        }
        hits = IndexPaginate("ta_downscale", data, size=1000).get_results()
        return {
            os.path.basename(hit["tmp_file_path"])
            for hit in hits
            if hit.get("tmp_file_path")
        }

    @staticmethod
    def get_next_queued(limit: int | None) -> list[dict]:
        """
        limit None means unlimited concurrency, still capped like every
        other "get everything" query here. A job stays status=queued
        from the moment it is dispatched until its task reaches
        _reserve_slot(), so status alone cannot tell "never dispatched"
        from "dispatched a moment ago" - without the empty task_id two
        dispatch passes close together could start two tasks for one
        doc.
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
        remote jobs (worker != "") are excluded: downscale_max_concurrent
        protects the TA host's own CPU and has nothing to say about a
        remote worker's hardware
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
        one update_by_query rather than a round-trip per job - a restart
        sweep can be resetting hundreds. Remote-held jobs are left
        alone.
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
        """pass exclude_id to ignore a job's own doc"""
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
        remote-held running jobs whose last_heartbeat predates
        stale_before: a crashed or powered-off worker never renewed its
        lease
        """
        data = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"status": {"value": "running"}}},
                        # ES reads a bare numeric on a date field as
                        # epoch millis, so without the format every
                        # epoch-second value looks like Jan 1970 and
                        # the range matches nothing
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
