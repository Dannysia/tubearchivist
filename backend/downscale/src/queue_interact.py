"""interact with items in the downscale review queue"""

import os
import uuid
from datetime import datetime

from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap


class DownscaleInteract:
    """interact with a single item in the downscale review queue"""

    def __init__(self, doc_id: str | None = None):
        self.doc_id = doc_id

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

    def get_item(self) -> tuple[dict | None, int]:
        """return job dict and status code"""
        path = f"ta_downscale/_doc/{self.doc_id}"
        response, status_code = ElasticWrap(path).get()
        return response.get("_source"), status_code

    def update(self, **fields) -> None:
        """partial update of job doc"""
        path = f"ta_downscale/_update/{self.doc_id}?refresh=true"
        ElasticWrap(path).post({"doc": fields})

    def delete_item(self) -> None:
        """delete job doc"""
        path = f"ta_downscale/_doc/{self.doc_id}"
        ElasticWrap(path).delete(refresh=True)

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
