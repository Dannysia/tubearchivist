"""
remote downscale worker API, see docs/remote-downscale/ta-server.md.

Every job-scoped endpoint identifies the calling worker from the request
body (JSON endpoints) or an X-TA-Worker header (the raw-body/no-body
endpoints), and returns 409 when the doc is no longer running or is held
by a different worker - the signal for the worker to abandon the job.
"""

from common.views_base import AdminOnly, ApiBaseView
from downscale.serializers import (
    WorkerClaimRequestSerializer,
    WorkerClaimResponseSerializer,
    WorkerErrorSerializer,
    WorkerFailRequestSerializer,
    WorkerFinishRequestSerializer,
    WorkerHeartbeatRequestSerializer,
    WorkerHeartbeatResponseSerializer,
)
from downscale.src import worker as worker_logic
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response


def _get_worker_name(request) -> str | None:
    """
    worker identity, from the X-TA-Worker header or a JSON body's
    "worker" field - a raw-body upload (PUT result) has no JSON to read,
    so it relies on the header alone
    """
    header = request.headers.get("X-TA-Worker")
    if header:
        return header

    if request.content_type == "application/json":
        return request.data.get("worker")

    return None


class DownscaleWorkerClaimView(ApiBaseView):
    """resolves to /api/downscale/worker/claim/
    POST: claim the oldest claimable queued job
    """

    permission_classes = [AdminOnly]

    @extend_schema(
        request=WorkerClaimRequestSerializer(),
        responses={
            200: OpenApiResponse(WorkerClaimResponseSerializer()),
            204: OpenApiResponse(description="nothing claimable"),
        },
    )
    def post(self, request):
        """claim the oldest claimable queued job for this worker"""
        data_serializer = WorkerClaimRequestSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        worker_name = data_serializer.validated_data["worker"]

        claimed = worker_logic.claim(worker_name)
        if not claimed:
            return Response(status=204)

        response_serializer = WorkerClaimResponseSerializer(claimed)
        return Response(response_serializer.data)


class DownscaleWorkerHeartbeatView(ApiBaseView):
    """resolves to /api/downscale/worker/jobs/<id>/heartbeat/
    POST: renew a job's lease and report progress
    """

    permission_classes = [AdminOnly]

    @extend_schema(
        request=WorkerHeartbeatRequestSerializer(),
        responses={
            200: OpenApiResponse(WorkerHeartbeatResponseSerializer()),
            409: OpenApiResponse(WorkerErrorSerializer()),
        },
    )
    def post(self, request, doc_id):
        """record a heartbeat, tell the worker whether to stop"""
        data_serializer = WorkerHeartbeatRequestSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        validated = data_serializer.validated_data

        result, error = worker_logic.heartbeat(
            doc_id, validated["worker"], validated["progress"]
        )
        if error:
            return Response({"error": error}, status=409)

        response_serializer = WorkerHeartbeatResponseSerializer(result)
        return Response(response_serializer.data)


class DownscaleWorkerResultView(ApiBaseView):
    """resolves to /api/downscale/worker/jobs/<id>/result/
    PUT: upload the encoded result, raw bytes in the request body
    """

    permission_classes = [AdminOnly]
    parser_classes = []

    @extend_schema(
        request={
            "application/octet-stream": {"type": "string", "format": "binary"}
        },
        responses={
            204: OpenApiResponse(description="uploaded"),
            409: OpenApiResponse(WorkerErrorSerializer()),
        },
    )
    def put(self, request, doc_id):
        """stream the request body to the job's tmp file"""
        worker_name = _get_worker_name(request)
        error = worker_logic.upload_result(doc_id, worker_name, request)
        if error:
            return Response({"error": error}, status=409)

        return Response(status=204)


class DownscaleWorkerFinishView(ApiBaseView):
    """resolves to /api/downscale/worker/jobs/<id>/finish/
    POST: report a successful encode, uploaded via result/ beforehand
    """

    permission_classes = [AdminOnly]

    @extend_schema(
        request=WorkerFinishRequestSerializer(),
        responses={
            200: OpenApiResponse(description="ok"),
            409: OpenApiResponse(WorkerErrorSerializer()),
        },
    )
    def post(self, request, doc_id):
        """validate the uploaded result and move the job to pending_review"""
        data_serializer = WorkerFinishRequestSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        validated = data_serializer.validated_data

        error = worker_logic.finish(
            doc_id,
            validated["worker"],
            validated["encoder"],
            validated["quality"],
            validated.get("preset"),
            validated["ffmpeg_args"],
            validated.get("container"),
        )
        if error:
            return Response({"error": error}, status=409)

        return Response({"ok": True})


class DownscaleWorkerFailView(ApiBaseView):
    """resolves to /api/downscale/worker/jobs/<id>/fail/
    POST: report an encode failure
    """

    permission_classes = [AdminOnly]

    @extend_schema(
        request=WorkerFailRequestSerializer(),
        responses={
            200: OpenApiResponse(description="ok"),
            409: OpenApiResponse(WorkerErrorSerializer()),
        },
    )
    def post(self, request, doc_id):
        """mark a job failed and clear the worker lease"""
        data_serializer = WorkerFailRequestSerializer(data=request.data)
        data_serializer.is_valid(raise_exception=True)
        validated = data_serializer.validated_data

        error = worker_logic.fail(
            doc_id, validated["worker"], validated["message"]
        )
        if error:
            return Response({"error": error}, status=409)

        return Response({"ok": True})


class DownscaleWorkerDeleteView(ApiBaseView):
    """resolves to /api/downscale/worker/jobs/<id>/
    DELETE: acknowledge a stop request, or abandon a job
    """

    permission_classes = [AdminOnly]

    @extend_schema(
        responses={
            204: OpenApiResponse(description="deleted"),
            409: OpenApiResponse(WorkerErrorSerializer()),
        },
    )
    def delete(self, request, doc_id):
        """delete an abandoned/acknowledged-stop job"""
        worker_name = _get_worker_name(request)
        error = worker_logic.delete(doc_id, worker_name)
        if error:
            return Response({"error": error}, status=409)

        return Response(status=204)
