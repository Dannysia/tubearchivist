"""interact with queue items"""

from common.src.es_connect import IndexWriteError
from common.src.queue_interact import BaseQueueInteract


class PendingInteract(BaseQueueInteract):
    """interact with items in download queue"""

    INDEX_NAME = "ta_download"

    def __init__(self, youtube_id=None, status=None):
        super().__init__(doc_id=youtube_id, status=status)

    def clear_indexed(self) -> None:
        try:
            self.delete_item(print_error=False)
        except IndexWriteError as err:
            print(f"{self.doc_id}: queue entry not cleared: {err}")

    def delete_bulk(self, channel_id: str | None, vid_type: str | None):
        """delete all matching item by status"""
        must_list = [{"term": {"status": {"value": self.status}}}]
        if channel_id:
            must_list.append({"term": {"channel_id": {"value": channel_id}}})

        if vid_type:
            must_list.append({"term": {"vid_type": {"value": vid_type}}})

        self._delete_by_query(must_list)

    def update_bulk(
        self,
        channel_id: str | None,
        vid_type: str | None,
        new_status: str,
        error: bool | None = None,
    ):
        """update status in bulk"""
        must_list = [{"term": {"status": {"value": self.status}}}]
        must_not_list = []

        if channel_id:
            must_list.append({"term": {"channel_id": {"value": channel_id}}})

        if vid_type:
            must_list.append({"term": {"vid_type": {"value": vid_type}}})

        if error is not None:
            exists = {"exists": {"field": "message"}}
            if error:
                must_list.append(exists)  # type: ignore
            else:
                must_not_list.append(exists)

        if new_status == "priority":
            source = """
            ctx._source.status = 'pending';
            ctx._source.auto_start = true;
            ctx._source.message = null;
            """
        elif new_status == "clear_error":
            source = "ctx._source.message = null"
        else:
            source = f"ctx._source.status = '{new_status}'"

        self._update_by_query(must_list, must_not_list, source)

    def update_status(self):
        """update status of pending item"""
        if self.status == "priority":
            self.update(status="pending", auto_start=True, message=None)
        else:
            self.update(status=self.status)
