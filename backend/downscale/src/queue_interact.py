"""interact with items in the downscale review queue"""

import uuid

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
    def get_active_for_video(youtube_id: str) -> dict | None:
        """return a running or pending_review job for this video, if any"""
        data = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"youtube_id": {"value": youtube_id}}},
                        {"terms": {"status": ["running", "pending_review"]}},
                    ]
                }
            },
            "size": 1,
        }
        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        hits = response["hits"]["hits"]
        if not hits:
            return None

        return {"id": hits[0]["_id"], **hits[0]["_source"]}
