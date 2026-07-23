"""interact with items in the extraction queue"""

from common.src.es_connect import ElasticWrap


class ExtractionInteract:
    """interact with items in ta_extraction"""

    def __init__(self, extraction_id=False, status=False):
        self.extraction_id = extraction_id
        self.status = status

    def delete_item(self):
        """delete single item from extraction queue"""
        path = f"ta_extraction/_doc/{self.extraction_id}"
        _, _ = ElasticWrap(path).delete(refresh=True)

    def delete_bulk(self, item_type: str | None = None):
        """delete all matching items by status"""
        must_list = [{"term": {"status": {"value": self.status}}}]
        if item_type:
            must_list.append({"term": {"item_type": {"value": item_type}}})

        data = {"query": {"bool": {"must": must_list}}}

        path = "ta_extraction/_delete_by_query?refresh=true"
        _, _ = ElasticWrap(path).post(data=data)

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

        data = {
            "query": {"bool": {"must": must_list, "must_not": must_not_list}},
            "script": {"source": source, "lang": "painless"},
        }

        path = "ta_extraction/_update_by_query?refresh=true"
        _, _ = ElasticWrap(path).post(data)

    def mark_extracting(self):
        """flip status to extracting"""
        data = {"doc": {"status": "extracting"}}
        path = f"ta_extraction/_update/{self.extraction_id}/?refresh=true"
        _, _ = ElasticWrap(path).post(data=data)

    def mark_failed(self, message: str):
        """flip status to failed with error message"""
        data = {"doc": {"status": "failed", "message": message}}
        path = f"ta_extraction/_update/{self.extraction_id}/?refresh=true"
        _, _ = ElasticWrap(path).post(data=data)

    def get_item(self):
        """return extraction item dict"""
        path = f"ta_extraction/_doc/{self.extraction_id}"
        response, status_code = ElasticWrap(path).get()
        return response["_source"], status_code
