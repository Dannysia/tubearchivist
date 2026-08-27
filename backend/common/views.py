"""all API views"""

from appsettings.src.config import ReleaseVersion
from appsettings.src.reindex import ReindexProgress
from common.serializers import (
    AsyncTaskResponseSerializer,
    ErrorResponseSerializer,
    LogDeleteQuerySerializer,
    LogDeleteResultSerializer,
    LogListSerializer,
    LogQueryFilterSerializer,
    NotificationQueryFilterSerializer,
    NotificationSerializer,
    PingSerializer,
    RefreshAddDataSerializer,
    RefreshAddQuerySerializer,
    RefreshQuerySerializer,
    RefreshResponseSerializer,
    WatchedDataSerializer,
)
from common.src.es_connect import ElasticWrap
from common.src.log import clear_logs
from common.src.search_processor import SearchProcess
from common.src.searching import SearchForm
from common.src.ta_redis import RedisArchivist
from common.src.watched import WatchState
from common.views_base import AdminOnly, ApiBaseView
from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView
from task.tasks import check_reindex


class PingView(ApiBaseView):
    """resolves to /api/ping/
    GET: test your connection
    """

    @staticmethod
    @extend_schema(
        responses={200: OpenApiResponse(PingSerializer())},
    )
    def get(request):
        """get pong"""
        data = {
            "response": "pong",
            "user": request.user.id,
            "version": ReleaseVersion().get_local_version(),
            "build_sha": settings.TA_BUILD_SHA,
            "build_date": settings.TA_BUILD_DATE,
            "ta_update": ReleaseVersion().get_update(),
        }
        serializer = PingSerializer(data)
        return Response(serializer.data)


class RefreshView(ApiBaseView):
    """resolves to /api/refresh/
    GET: get refresh progress
    POST: start a manual refresh task
    """

    permission_classes = [AdminOnly]

    @extend_schema(
        responses={
            200: OpenApiResponse(RefreshResponseSerializer()),
            400: OpenApiResponse(
                ErrorResponseSerializer(), description="Bad request"
            ),
        },
        parameters=[RefreshQuerySerializer()],
    )
    def get(self, request):
        """get refresh status"""
        query_serializer = RefreshQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data
        request_type = validated_query.get("type")
        request_id = validated_query.get("id")

        if request_id and not request_type:
            error = ErrorResponseSerializer(
                {"error": "specified id also needs type"}
            )
            return Response(error.data, status=400)

        try:
            progress = ReindexProgress(
                request_type=request_type, request_id=request_id
            ).get_progress()
        except ValueError:
            error = ErrorResponseSerializer({"error": "bad request"})
            return Response(error.data, status=400)

        response_serializer = RefreshResponseSerializer(progress)

        return Response(response_serializer.data)

    @extend_schema(
        request=RefreshAddDataSerializer(),
        responses={
            200: OpenApiResponse(AsyncTaskResponseSerializer()),
        },
        parameters=[RefreshAddQuerySerializer()],
    )
    def post(self, request):
        """add to reindex queue"""
        query_serializer = RefreshAddQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data

        data_serializer = RefreshAddDataSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        validated_data = data_serializer.validated_data

        extract_videos = validated_query.get("extract_videos")
        task = check_reindex.delay(
            data=validated_data, extract_videos=extract_videos
        )
        message = {
            "message": "reindex task started",
            "task_id": task.id,
        }
        serializer = AsyncTaskResponseSerializer(message)

        return Response(serializer.data)


class WatchedView(ApiBaseView):
    """resolves to /api/watched/
    POST: change watched state of video, channel or playlist
    """

    @extend_schema(
        request=WatchedDataSerializer(),
        responses={
            200: OpenApiResponse(WatchedDataSerializer()),
            400: OpenApiResponse(
                ErrorResponseSerializer(), description="Bad request"
            ),
        },
    )
    def post(self, request):
        """change watched state"""
        data_serializer = WatchedDataSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        validated_data = data_serializer.validated_data
        youtube_id = validated_data.get("id")
        is_watched = validated_data.get("is_watched")

        if not youtube_id or is_watched is None:
            error = ErrorResponseSerializer(
                {"error": "missing id or is_watched"}
            )
            return Response(error.data, status=400)

        WatchState(youtube_id, is_watched, request.user.id).change()
        return Response(data_serializer.data)


class SearchView(ApiBaseView):
    """resolves to /api/search/
    GET: run a search with the string in the ?query parameter
    """

    @staticmethod
    def get(request):
        """handle get request
        search through all indexes"""
        search_query = request.GET.get("query", None)
        if search_query is None:
            return Response(
                {"message": "no search query specified"}, status=400
            )

        search_results = SearchForm().multi_search(search_query)
        return Response(search_results)


class NotificationView(ApiBaseView):
    """resolves to /api/notification/
    GET: returns a list of notifications
    filter query to filter messages by group
    """

    valid_filters = ["download", "settings", "channel", "downscale"]

    @extend_schema(
        responses={
            200: OpenApiResponse(NotificationSerializer(many=True)),
        },
        parameters=[NotificationQueryFilterSerializer],
    )
    def get(self, request):
        """get all notifications"""
        query_serializer = NotificationQueryFilterSerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data
        filter_by = validated_query.get("filter")

        query = "message"
        if filter_by in self.valid_filters:
            query = f"{query}:{filter_by}"

        notifications = RedisArchivist().list_items(query)
        response_serializer = NotificationSerializer(notifications, many=True)

        return Response(response_serializer.data)


class HealthCheck(APIView):
    """health check view, no auth needed"""

    def get(self, request):
        """health check, no auth needed"""
        return Response("OK", status=200)


class LogView(ApiBaseView):
    """resolves to /api/log/
    GET: return stored log entries, newest first
    DELETE: clear stored log entries
    """

    search_base = "ta_log/_search"
    permission_classes = [AdminOnly]

    @staticmethod
    def _build_must_list(validated_query: dict) -> list[dict]:
        """build the filter part of the query"""
        must_list: list[dict] = []
        for field in ("source", "level", "task_name"):
            value = validated_query.get(field)
            if value:
                must_list.append({"term": {field: {"value": value}}})

        query_str = validated_query.get("q")
        if query_str:
            must_list.append({"match": {"message": {"query": query_str}}})

        return must_list

    @extend_schema(
        parameters=[LogQueryFilterSerializer()],
        responses={200: OpenApiResponse(LogListSerializer())},
    )
    def get(self, request):
        """get log entries"""
        query_serializer = LogQueryFilterSerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        validated_query = query_serializer.validated_data

        must_list = self._build_must_list(validated_query)
        if must_list:
            self.data["query"] = {"bool": {"must": must_list}}

        self.data["sort"] = [{"timestamp": {"order": "desc"}}]
        self.data["aggs"] = self._build_task_aggs(validated_query)
        self.initiate_pagination(request)

        response, _ = ElasticWrap(self.search_base).get(data=self.data)
        # deliberately not get_document_list: that 404s on an empty
        # result, and an empty log is the normal state of a fresh
        # install rather than a missing page
        hits = response.get("hits", {})
        self.pagination_handler.validate(hits.get("total", {}).get("value", 0))
        serializer = LogListSerializer(
            {
                "data": SearchProcess(response).process() or [],
                "paginate": self.pagination_handler.pagination,
                "tasks": self._parse_task_aggs(response),
            }
        )

        return Response(serializer.data)

    @staticmethod
    def _build_task_aggs(validated_query: dict) -> dict:
        """
        build the aggs for the task filter dropdown

        Deliberately scoped to the source alone rather than the active
        filters: an agg over the current result set would drop every
        other task the moment one is picked, leaving no way back to
        them, and would miss any task whose entries all sit on a later
        page. With no source given the list spans every source, exactly
        as the unfiltered result set does.
        """
        source = validated_query.get("source")
        source_filter: dict = (
            {"term": {"source": {"value": source}}}
            if source
            else {"match_all": {}}
        )

        return {
            "all": {
                "global": {},
                "aggs": {
                    "in_source": {
                        "filter": source_filter,
                        "aggs": {
                            "tasks": {
                                "multi_terms": {
                                    "size": 50,
                                    "terms": [
                                        {"field": "task_name"},
                                        # multi_terms drops a document
                                        # missing any of its fields, and
                                        # a task with no TASK_CONFIG
                                        # entry logs without a title.
                                        # Without this it would have
                                        # rows in the log that the
                                        # filter could not select
                                        {"field": "task_title", "missing": ""},
                                    ],
                                    "order": {"_count": "desc"},
                                }
                            }
                        },
                    }
                },
            }
        }

    @staticmethod
    def _parse_task_aggs(response: dict) -> list[dict]:
        """pull the task name/title pairs back out of the agg response"""
        buckets = (
            response.get("aggregations", {})
            .get("all", {})
            .get("in_source", {})
            .get("tasks", {})
            .get("buckets", [])
        )

        return [
            {"task_name": i["key"][0], "task_title": i["key"][1]}
            for i in buckets
        ]

    @extend_schema(
        parameters=[LogDeleteQuerySerializer()],
        responses={200: OpenApiResponse(LogDeleteResultSerializer())},
    )
    def delete(self, request):
        """clear log entries, optionally limited to one source"""
        query_serializer = LogDeleteQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        source = query_serializer.validated_data.get("source")

        deleted = clear_logs(source)
        serializer = LogDeleteResultSerializer({"deleted": deleted})

        return Response(serializer.data)
