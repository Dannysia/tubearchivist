from common.src.queue_interact import BaseQueueInteract


class ExtractionInteract(BaseQueueInteract):
    INDEX_NAME = "ta_extraction"

    def delete_bulk(self, item_type: str | None = None):
        must_list = [{"term": {"status": {"value": self.status}}}]
        if item_type:
            must_list.append({"term": {"item_type": {"value": item_type}}})

        self._delete_by_query(must_list)

    def update_bulk(
        self,
        item_type: str | None,
        new_status: str,
        error: bool | None = None,
    ):
        must_list = [{"term": {"status": {"value": self.status}}}]
        must_not_list = []

        if item_type:
            must_list.append({"term": {"item_type": {"value": item_type}}})

        if error is not None:
            exists = {"exists": {"field": "message"}}
            if error:
                must_list.append(exists)  # type: ignore
            else:
                must_not_list.append(exists)

        if new_status == "clear_error":
            source = """
            ctx._source.status = 'pending';
            ctx._source.message = null;
            """
        else:
            source = f"ctx._source.status = '{new_status}'"

        self._update_by_query(must_list, must_not_list, source)

    def mark_extracting(self):
        self.update(status="extracting")

    def mark_failed(self, message: str):
        self.update(status="failed", message=message)
