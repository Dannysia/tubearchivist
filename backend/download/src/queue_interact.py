"""interact with queue items"""

from common.src.es_connect import ElasticWrap
from common.src.queue_interact import BaseQueueInteract


class PendingInteract(BaseQueueInteract):
    """interact with items in download queue"""

    INDEX_NAME = "ta_download"

    def __init__(self, youtube_id=None, status=None):
        super().__init__(doc_id=youtube_id, status=status)

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

    def get_channel(self):
        """
        get channel metadata from queue to not depend on channel to be indexed
        """
        data = {
            "size": 1,
            "query": {"term": {"channel_id": {"value": self.doc_id}}},
        }
        response, _ = ElasticWrap("ta_download/_search").get(data=data)
        hits = response["hits"]["hits"]
        if not hits:
            channel_name = "NA"
        else:
            channel_name = hits[0]["_source"].get("channel_name", "NA")

        return {
            "channel_id": self.doc_id,
            "channel_name": channel_name,
        }
