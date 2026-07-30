"""all downscale queue API views"""

from common.src.es_connect import ElasticWrap
from common.views_base import AdminOnly, ApiBaseView
from downscale.serializers import (
    DownscaleAggsQuerySerializer,
    DownscaleAggsSerializer,
    DownscaleBulkActionSerializer,
    DownscaleBulkResultSerializer,
    DownscaleEncoderTestSerializer,
    DownscaleListQuerySerializer,
    DownscaleListSerializer,
)
from downscale.src.downscale import DownscaleReview
from downscale.src.encoder_capability import EncoderCapabilityTest
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response

# practical downscale queues stay small (same size cap already used
# elsewhere for "get everything matching" queries, e.g.
# DownscaleInteract.get_interrupted/get_all_tmp_filenames)
BULK_BY_FILTER_MAX = 1000


def _build_must_list(validated_query: dict) -> list[dict]:
    """
    build the bool-query must clauses for the list/status/channel/search/
    size_change filters, shared between listing and resolving ids for a
    bulk-by-filter action
    """
    must_list = []
    status_filter = validated_query.get("status")
    if status_filter:
        must_list.append({"term": {"status": {"value": status_filter}}})

    channel_filter = validated_query.get("channel")
    if channel_filter:
        must_list.append({"term": {"channel_id": {"value": channel_filter}}})

    search_query = validated_query.get("q")
    if search_query:
        must_list.append({"match_phrase_prefix": {"title": search_query}})

    size_change = validated_query.get("size_change")
    if size_change:
        # new_size is only ever set once an encode actually finishes
        # (_finish_success), so requiring > 0 excludes queued/running/
        # failed jobs rather than treating their unset 0 as "smaller"
        operator = "<" if size_change == "smaller" else ">"
        must_list.append(
            {
                "script": {
                    "script": {
                        "source": (
                            "doc['new_size'].size() > 0 && "
                            "doc['new_size'].value > 0 && "
                            f"doc['new_size'].value {operator} "
                            "doc['original_size'].value"
                        )
                    }
                }
            }
        )

    return must_list


class DownscaleApiListView(ApiBaseView):
    """resolves to /api/downscale/
    GET: return the downscale review queue
    POST: bulk accept/reject/retry/cancel jobs, by id or by list filter
    """

    search_base = "ta_downscale/_search/"
    permission_classes = [AdminOnly]

    @extend_schema(
        parameters=[DownscaleListQuerySerializer()],
        responses={200: OpenApiResponse(DownscaleListSerializer())},
    )
    def get(self, request):
        """get downscale queue list"""
        query_serializer = DownscaleListQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data

        self.data.update({"sort": [{"timestamp": {"order": "desc"}}]})

        must_list = _build_must_list(validated_query)
        if must_list:
            self.data["query"] = {"bool": {"must": must_list}}

        self.get_document_list(request)
        serializer = DownscaleListSerializer(self.response)

        return Response(serializer.data)

    @extend_schema(
        request=DownscaleBulkActionSerializer(),
        parameters=[DownscaleListQuerySerializer()],
        responses={200: OpenApiResponse(DownscaleBulkResultSerializer())},
    )
    def post(self, request):
        """
        bulk accept/reject/retry/cancel downscale jobs. Pass explicit ids,
        or omit ids and pass the same status/channel/q/size_change query
        params as GET to act on everything currently matching that filter.
        """
        data_serializer = DownscaleBulkActionSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        validated_data = data_serializer.validated_data

        action = validated_data["action"]
        ids = validated_data.get("ids")
        if not ids:
            ids = self._get_ids_by_filter(request)

        success: list[str] = []
        failed: list[dict] = []
        for doc_id in ids:
            review = DownscaleReview(doc_id)
            error = getattr(review, action)()
            if error:
                failed.append({"id": doc_id, "error": error})
            else:
                success.append(doc_id)

        response_serializer = DownscaleBulkResultSerializer(
            {"success": success, "failed": failed}
        )

        return Response(response_serializer.data)

    @staticmethod
    def _get_ids_by_filter(request) -> list[str]:
        """resolve doc ids matching the current list filter query params"""
        query_serializer = DownscaleListQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data

        data: dict = {"size": BULK_BY_FILTER_MAX, "_source": False}
        must_list = _build_must_list(validated_query)
        if must_list:
            data["query"] = {"bool": {"must": must_list}}

        response, _ = ElasticWrap("ta_downscale/_search").get(data=data)
        return [hit["_id"] for hit in response.get("hits", {}).get("hits", [])]


class DownscaleAggsApiView(ApiBaseView):
    """resolves to /api/downscale/aggs/
    GET: get channel aggregations for the downscale queue
    """

    search_base = "ta_downscale/_search"
    permission_classes = [AdminOnly]

    @extend_schema(
        parameters=[DownscaleAggsQuerySerializer()],
        responses={200: OpenApiResponse(DownscaleAggsSerializer())},
    )
    def get(self, request):
        """get aggs"""
        query_serializer = DownscaleAggsQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data

        status_filter = validated_query.get("status")
        if status_filter:
            self.data["query"] = {
                "term": {"status": {"value": status_filter}}
            }

        self.data.update(
            {
                "aggs": {
                    "channel_downscale": {
                        "multi_terms": {
                            "size": 30,
                            "terms": [
                                {"field": "channel_name.keyword"},
                                {"field": "channel_id"},
                            ],
                            "order": {"_count": "desc"},
                        }
                    }
                }
            }
        )
        self.get_aggs()
        serializer = DownscaleAggsSerializer(self.response["channel_downscale"])

        return Response(serializer.data)


class DownscaleEncoderTestApiView(ApiBaseView):
    """resolves to /api/downscale/test-encoders/
    POST: run a small test encode for each hardware encoder
    """

    permission_classes = [AdminOnly]

    @extend_schema(
        responses={
            200: OpenApiResponse(DownscaleEncoderTestSerializer(many=True))
        },
    )
    def post(self, request):
        """test hardware encoders with a small synthetic encode"""
        results = EncoderCapabilityTest().run()
        serializer = DownscaleEncoderTestSerializer(results, many=True)

        return Response(serializer.data)
