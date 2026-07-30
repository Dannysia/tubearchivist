"""all downscale queue API views"""

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


class DownscaleApiListView(ApiBaseView):
    """resolves to /api/downscale/
    GET: return the downscale review queue
    POST: bulk accept/reject/retry jobs by id
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

        must_list = []
        status_filter = validated_query.get("status")
        if status_filter:
            must_list.append({"term": {"status": {"value": status_filter}}})

        channel_filter = validated_query.get("channel")
        if channel_filter:
            must_list.append(
                {"term": {"channel_id": {"value": channel_filter}}}
            )

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

        if must_list:
            self.data["query"] = {"bool": {"must": must_list}}

        self.get_document_list(request)
        serializer = DownscaleListSerializer(self.response)

        return Response(serializer.data)

    @extend_schema(
        request=DownscaleBulkActionSerializer(),
        responses={200: OpenApiResponse(DownscaleBulkResultSerializer())},
    )
    def post(self, request):
        """bulk accept/reject/retry downscale jobs"""
        data_serializer = DownscaleBulkActionSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        validated_data = data_serializer.validated_data

        action = validated_data["action"]
        success: list[str] = []
        failed: list[dict] = []
        for doc_id in validated_data["ids"]:
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
