"""interact with items in the extraction queue"""

from common.src.queue_interact import BaseQueueInteract


class ExtractionInteract(BaseQueueInteract):
    """interact with items in ta_extraction"""

    INDEX_NAME = "ta_extraction"

    def delete_bulk(self, item_type: str | None = None):
        """delete all matching items by status"""
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
        """update status in bulk"""
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
        """flip status to extracting"""
        self.update(status="extracting")

    def mark_failed(self, message: str):
        """flip status to failed with error message"""
        self.update(status="failed", message=message)
