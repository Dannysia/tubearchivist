from common.src.es_connect import ElasticWrap


class QueueWriteError(Exception):
    pass


class QueueDocMissing(QueueWriteError):
    pass


class BaseQueueInteract:
    INDEX_NAME: str = ""

    def __init__(self, doc_id=None, status=None):
        self.doc_id = doc_id
        self.status = status

    def get_item(self) -> tuple[dict | None, int]:
        path = f"{self.INDEX_NAME}/_doc/{self.doc_id}"
        response, status_code = ElasticWrap(path).get()
        return response.get("_source"), status_code

    def _check(self, response, status_code: int, what: str) -> None:
        if status_code not in (200, 201):
            raise QueueWriteError(
                f"{self.INDEX_NAME}: {what} failed, "
                f"es answered {status_code}: {response}"
            )

        # a by-query call answers 200 and reports per document failures
        # in the body
        failures = response.get("failures") if response else None
        if failures:
            raise QueueWriteError(
                f"{self.INDEX_NAME}: {what} left {len(failures)} "
                f"documents unwritten: {failures[:3]}"
            )

    def delete_item(self, print_error: bool = True) -> None:
        path = f"{self.INDEX_NAME}/_doc/{self.doc_id}"
        response, status_code = ElasticWrap(path).delete(
            refresh=True, print_error=print_error
        )
        # 404 is the state this asks for, so it is not a failure
        if status_code == 404:
            return

        self._check(response, status_code, f"delete {self.doc_id}")

    def update(self, **fields) -> None:
        path = f"{self.INDEX_NAME}/_update/{self.doc_id}?refresh=true"
        response, status_code = ElasticWrap(path).post({"doc": fields})
        if status_code == 404:
            raise QueueDocMissing(
                f"{self.INDEX_NAME}: {self.doc_id} is not in the index"
            )

        self._check(response, status_code, f"update {self.doc_id}")

    def _delete_by_query(self, must_list: list[dict]) -> None:
        data = {"query": {"bool": {"must": must_list}}}
        path = f"{self.INDEX_NAME}/_delete_by_query?refresh=true"
        response, status_code = ElasticWrap(path).post(data=data)
        self._check(response, status_code, "delete by query")

    def _update_by_query(
        self,
        must_list: list[dict],
        must_not_list: list[dict],
        script_source: str,
    ) -> None:
        data = {
            "query": {"bool": {"must": must_list, "must_not": must_not_list}},
            "script": {"source": script_source, "lang": "painless"},
        }
        path = f"{self.INDEX_NAME}/_update_by_query?refresh=true"
        response, status_code = ElasticWrap(path).post(data)
        self._check(response, status_code, "update by query")
