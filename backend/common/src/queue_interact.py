"""
Functionality:
- shared base for interacting with a single status-tracked ES queue index
- used by the download pending, extraction, and downscale queues
"""

from common.src.es_connect import ElasticWrap


class BaseQueueInteract:
    """get/update/delete a single item, or bulk update/delete by query"""

    INDEX_NAME: str = ""

    def __init__(self, doc_id=None, status=None):
        self.doc_id = doc_id
        self.status = status

    def get_item(self) -> tuple[dict | None, int]:
        """return item dict and status code"""
        path = f"{self.INDEX_NAME}/_doc/{self.doc_id}"
        response, status_code = ElasticWrap(path).get()
        return response.get("_source"), status_code

    def delete_item(self) -> None:
        """delete single item from the queue"""
        path = f"{self.INDEX_NAME}/_doc/{self.doc_id}"
        ElasticWrap(path).delete(refresh=True)

    def update(self, **fields) -> None:
        """partial update of a single item doc"""
        path = f"{self.INDEX_NAME}/_update/{self.doc_id}?refresh=true"
        ElasticWrap(path).post({"doc": fields})

    def _delete_by_query(self, must_list: list[dict]) -> None:
        """delete all items matching must_list, validate before"""
        data = {"query": {"bool": {"must": must_list}}}
        path = f"{self.INDEX_NAME}/_delete_by_query?refresh=true"
        ElasticWrap(path).post(data=data)

    def _update_by_query(
        self,
        must_list: list[dict],
        must_not_list: list[dict],
        script_source: str,
    ) -> None:
        """bulk update all items matching the query, validate before"""
        data = {
            "query": {"bool": {"must": must_list, "must_not": must_not_list}},
            "script": {"source": script_source, "lang": "painless"},
        }
        path = f"{self.INDEX_NAME}/_update_by_query?refresh=true"
        ElasticWrap(path).post(data)
