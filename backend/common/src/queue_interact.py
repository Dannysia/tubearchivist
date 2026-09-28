from common.src.es_connect import ElasticWrap


class BaseQueueInteract:
    INDEX_NAME: str = ""

    def __init__(self, doc_id=None, status=None):
        self.doc_id = doc_id
        self.status = status

    def get_item(self) -> tuple[dict | None, int]:
        path = f"{self.INDEX_NAME}/_doc/{self.doc_id}"
        response, status_code = ElasticWrap(path).get()
        return response.get("_source"), status_code

    def delete_item(self, print_error: bool = True) -> None:
        path = f"{self.INDEX_NAME}/_doc/{self.doc_id}"
        ElasticWrap(path).delete(refresh=True, print_error=print_error)

    def update(self, **fields) -> None:
        """partial update, not a replace"""
        path = f"{self.INDEX_NAME}/_update/{self.doc_id}?refresh=true"
        ElasticWrap(path).post({"doc": fields})

    def _delete_by_query(self, must_list: list[dict]) -> None:
        """validate must_list before calling"""
        data = {"query": {"bool": {"must": must_list}}}
        path = f"{self.INDEX_NAME}/_delete_by_query?refresh=true"
        ElasticWrap(path).post(data=data)

    def _update_by_query(
        self,
        must_list: list[dict],
        must_not_list: list[dict],
        script_source: str,
    ) -> None:
        """validate the query before calling"""
        data = {
            "query": {"bool": {"must": must_list, "must_not": must_not_list}},
            "script": {"source": script_source, "lang": "painless"},
        }
        path = f"{self.INDEX_NAME}/_update_by_query?refresh=true"
        ElasticWrap(path).post(data)
