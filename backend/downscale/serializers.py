"""downscale serializers"""

# pylint: disable=abstract-method

from common.serializers import PaginationSerializer
from rest_framework import serializers


class DownscaleItemSerializer(serializers.Serializer):
    """serialize downscale queue item"""

    id = serializers.CharField()
    youtube_id = serializers.CharField()
    channel_id = serializers.CharField()
    channel_name = serializers.CharField()
    title = serializers.CharField()
    vid_thumb_url = serializers.CharField(allow_null=True)
    media_url = serializers.CharField()
    status = serializers.ChoiceField(
        choices=["queued", "running", "pending_review", "failed", "cancelled"]
    )
    current_height = serializers.IntegerField()
    target_height = serializers.IntegerField()
    original_size = serializers.IntegerField()
    new_size = serializers.IntegerField()
    tmp_file_path = serializers.CharField()
    task_id = serializers.CharField()
    timestamp = serializers.IntegerField()
    updated = serializers.IntegerField()
    message = serializers.CharField(required=False, allow_null=True)
    encoder = serializers.CharField(required=False, allow_null=True)
    quality = serializers.IntegerField(required=False, allow_null=True)
    preset = serializers.CharField(required=False, allow_null=True)
    ffmpeg_args = serializers.CharField(required=False, allow_null=True)
    progress = serializers.FloatField(required=False, allow_null=True)
    _index = serializers.CharField(required=False)
    _score = serializers.IntegerField(required=False)


class DownscaleListSerializer(serializers.Serializer):
    """serialize downscale queue list"""

    data = DownscaleItemSerializer(many=True)
    paginate = PaginationSerializer()


class DownscaleListQuerySerializer(serializers.Serializer):
    """serialize query params for downscale list"""

    status = serializers.ChoiceField(
        choices=["queued", "running", "pending_review", "failed", "cancelled"],
        required=False,
    )
    channel = serializers.CharField(required=False, help_text="channel ID")
    q = serializers.CharField(required=False, help_text="Search Query")
    size_change = serializers.ChoiceField(
        choices=["smaller", "larger"],
        required=False,
        help_text="only jobs where the encode finished smaller/larger",
    )
    page = serializers.IntegerField(required=False)


class DownscaleBulkActionSerializer(serializers.Serializer):
    """
    serialize bulk accept/reject/retry/cancel request. ids is optional -
    when omitted, the action applies to everything matching the query
    filter instead (see DownscaleListQuerySerializer)
    """

    ids = serializers.ListField(child=serializers.CharField(), required=False)
    action = serializers.ChoiceField(
        choices=["accept", "reject", "retry", "cancel"]
    )


class DownscaleBulkResultItemSerializer(serializers.Serializer):
    """serialize a single failed bulk action item"""

    id = serializers.CharField()
    error = serializers.CharField()


class DownscaleBulkResultSerializer(serializers.Serializer):
    """serialize bulk accept/reject response"""

    success = serializers.ListField(child=serializers.CharField())
    failed = DownscaleBulkResultItemSerializer(many=True)


class DownscaleEncoderTestSerializer(serializers.Serializer):
    """serialize a single hardware encoder capability test result"""

    encoder = serializers.CharField()
    ok = serializers.BooleanField()
    message = serializers.CharField(allow_null=True)


class DownscaleAggsQuerySerializer(serializers.Serializer):
    """serialize query params for downscale aggs"""

    status = serializers.ChoiceField(
        choices=["queued", "running", "pending_review", "failed", "cancelled"],
        required=False,
    )


class WorkerClaimRequestSerializer(serializers.Serializer):
    """serialize a remote worker's claim request"""

    worker = serializers.CharField()
    encoders = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="for logging/debugging only, TA does not act on it",
    )


class WorkerClaimResponseSerializer(serializers.Serializer):
    """serialize the job handed to a remote worker on a successful claim"""

    id = serializers.CharField()
    youtube_id = serializers.CharField()
    title = serializers.CharField()
    target_height = serializers.IntegerField()
    quality_hint = serializers.IntegerField()
    source_url = serializers.CharField()


class WorkerJobActionRequestSerializer(serializers.Serializer):
    """serialize the worker identity carried by every job-scoped request"""

    worker = serializers.CharField()


class WorkerHeartbeatRequestSerializer(WorkerJobActionRequestSerializer):
    """serialize a remote worker's heartbeat/progress update"""

    progress = serializers.FloatField(min_value=0, max_value=1)


class WorkerHeartbeatResponseSerializer(serializers.Serializer):
    """serialize the heartbeat response - whether the worker should stop"""

    stop = serializers.BooleanField()


class WorkerFinishRequestSerializer(WorkerJobActionRequestSerializer):
    """serialize a remote worker's finish report"""

    encoder = serializers.CharField()
    quality = serializers.IntegerField(allow_null=True)
    preset = serializers.CharField(allow_null=True, required=False)
    ffmpeg_args = serializers.CharField()


class WorkerFailRequestSerializer(WorkerJobActionRequestSerializer):
    """serialize a remote worker's failure report"""

    message = serializers.CharField(allow_blank=True)


class WorkerErrorSerializer(serializers.Serializer):
    """serialize a worker API error response"""

    error = serializers.CharField()


class DownscaleAggBucketSerializer(serializers.Serializer):
    """serialize bucket"""

    key = serializers.ListField(child=serializers.CharField())
    key_as_string = serializers.CharField()
    doc_count = serializers.IntegerField()


class DownscaleAggsSerializer(serializers.Serializer):
    """serialize downscale channel bucket aggregations"""

    doc_count_error_upper_bound = serializers.IntegerField()
    sum_other_doc_count = serializers.IntegerField()
    buckets = DownscaleAggBucketSerializer(many=True)
