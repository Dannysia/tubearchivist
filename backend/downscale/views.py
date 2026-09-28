from common.src.es_connect import ElasticWrap
from common.src.queue_interact import QueueWriteError
from common.views_base import AdminOnly, ApiBaseView
from downscale.serializers import (
    DownscaleAggsQuerySerializer,
    DownscaleAggsSerializer,
    DownscaleBulkActionSerializer,
    DownscaleBulkResultSerializer,
    DownscaleEncoderAggsSerializer,
    DownscaleEncoderTestSerializer,
    DownscaleListQuerySerializer,
    DownscaleListSerializer,
    DownscaleSavedAggsSerializer,
)
from downscale.src.constants import saved_percent_agg, size_change_clause
from downscale.src.downscale import (
    DownscaleReview,
    dispatch_pending_downscales,
)
from downscale.src.encoder_capability import EncoderCapabilityTest
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response

# practical downscale queues stay small; the same cap the other
# "get everything matching" queries use
BULK_BY_FILTER_MAX = 1000

# lead with what is actionable - running, then pending_review, then
# failed - ahead of the passive queued backlog, newest first within each
# group. Only applied unfiltered: one status makes the grouping a no-op.
_STATUS_SORT = [
    {
        "_script": {
            "type": "number",
            "order": "asc",
            "script": {
                "lang": "painless",
                "source": (
                    "def s = doc['status'].value;"
                    "if (s == 'running') return 0;"
                    "else if (s == 'pending_review') return 1;"
                    "else if (s == 'failed') return 2;"
                    "else if (s == 'queued') return 3;"
                    "else return 4;"
                ),
            },
        }
    },
    {"timestamp": {"order": "desc"}},
]


def _build_must_list(validated_query: dict) -> list[dict]:
    must_list = []
    status_filter = validated_query.get("status")
    if status_filter:
        must_list.append({"term": {"status": {"value": status_filter}}})

    channel_filter = validated_query.get("channel")
    if channel_filter:
        must_list.append({"term": {"channel_id": {"value": channel_filter}}})

    encoder_filter = validated_query.get("encoder")
    if encoder_filter:
        must_list.append({"term": {"encoder": {"value": encoder_filter}}})

    search_query = validated_query.get("q")
    if search_query:
        must_list.append({"match_phrase_prefix": {"title": search_query}})

    size_change = validated_query.get("size_change")
    if size_change:
        # new_size is only set once an encode finishes, so the clause
        # requires it > 0 rather than reading an unset 0 as "smaller"
        must_list.append(size_change_clause(size_change))

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

        must_list = _build_must_list(validated_query)
        if must_list:
            self.data["query"] = {"bool": {"must": must_list}}
            self.data["sort"] = [{"timestamp": {"order": "desc"}}]
        else:
            self.data["sort"] = _STATUS_SORT

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
            try:
                error = getattr(review, action)()
            except QueueWriteError as err:
                error = str(err)

            if error:
                failed.append({"id": doc_id, "error": error})
            else:
                success.append(doc_id)

        if action == "retry" and success:
            # retry() only resets docs to queued, so one dispatch pass
            # covers the whole batch
            dispatch_pending_downscales()

        response_serializer = DownscaleBulkResultSerializer(
            {"success": success, "failed": failed}
        )

        return Response(response_serializer.data)

    @staticmethod
    def _get_ids_by_filter(request) -> list[str]:
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


CHANNEL_AGGS_KEY = "channel_downscale"
ENCODER_AGGS_KEY = "encoder_downscale"
SAVED_AGGS_KEY = "saved_downscale"


def _build_aggs_query(field_filter: str) -> tuple[str, dict]:
    """
    returns (agg_key, agg_body); the caller needs agg_key to pull the
    bucket set back out of the ES response. channel is multi_terms
    because a display name and a filterable id are both needed. encoder
    is only ever set once a job finishes, so aggregating on it excludes
    queued and running jobs rather than bucketing them under "".
    """
    if field_filter == "encoder":
        return ENCODER_AGGS_KEY, {"terms": {"field": "encoder", "size": 30}}

    if field_filter == "saved":
        return SAVED_AGGS_KEY, saved_percent_agg()

    return CHANNEL_AGGS_KEY, {
        "multi_terms": {
            "size": 30,
            "terms": [
                {"field": "channel_name.keyword"},
                {"field": "channel_id"},
            ],
            "order": {"_count": "desc"},
        }
    }


class DownscaleAggsApiView(ApiBaseView):
    """resolves to /api/downscale/aggs/
    GET: get channel or encoder aggregations for the downscale queue
    """

    search_base = "ta_downscale/_search"
    permission_classes = [AdminOnly]

    @extend_schema(
        parameters=[DownscaleAggsQuerySerializer()],
        responses={200: OpenApiResponse(DownscaleAggsSerializer())},
    )
    def get(self, request):
        """get aggs, field=channel (default), encoder or saved"""
        query_serializer = DownscaleAggsQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data

        status_filter = validated_query.get("status")
        if status_filter:
            self.data["query"] = {"term": {"status": {"value": status_filter}}}

        field_filter = validated_query.get("field") or "channel"
        agg_key, agg_body = _build_aggs_query(field_filter)
        self.data["aggs"] = {agg_key: agg_body}
        self.get_aggs()

        if field_filter == "encoder":
            serializer = DownscaleEncoderAggsSerializer(self.response[agg_key])
        elif field_filter == "saved":
            serializer = DownscaleSavedAggsSerializer(self.response[agg_key])
        else:
            serializer = DownscaleAggsSerializer(self.response[agg_key])

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
