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
    encoder = serializers.CharField(
        required=False,
        help_text=(
            "exact encoder string (e.g. av1_nvenc, h264_vaapi) - only set "
            "once a job has actually run, so this excludes queued/running "
            "jobs regardless of match"
        ),
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
    field = serializers.ChoiceField(
        choices=["channel", "encoder"],
        required=False,
        help_text="which field to aggregate on, defaults to channel",
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
    container = serializers.RegexField(
        r"^[a-zA-Z0-9]{1,5}$",
        required=False,
        allow_null=True,
        help_text=(
            "extension (no dot) of the container the worker actually "
            "produced, e.g. mkv. tmp_file_path is fixed to .mp4 at enqueue "
            "time, before it's known whether a local or remote encode runs "
            "the job, so a worker producing something else has to say so "
            "here. Omit when the output really is .mp4. Restricted to "
            "alphanumerics so it can only ever swap an extension, never "
            "redirect the path"
        ),
    )


class WorkerFailRequestSerializer(WorkerJobActionRequestSerializer):
    """serialize a remote worker's failure report"""

    message = serializers.CharField(allow_blank=True)


class WorkerErrorSerializer(serializers.Serializer):
    """serialize a worker API error response"""

    error = serializers.CharField()


class DownscaleAggBucketSerializer(serializers.Serializer):
    """
    serialize a channel bucket - key is a (channel_name, channel_id) pair,
    the shape multi_terms always returns
    """

    key = serializers.ListField(child=serializers.CharField())
    key_as_string = serializers.CharField()
    doc_count = serializers.IntegerField()


class DownscaleAggsSerializer(serializers.Serializer):
    """serialize downscale channel bucket aggregations"""

    doc_count_error_upper_bound = serializers.IntegerField()
    sum_other_doc_count = serializers.IntegerField()
    buckets = DownscaleAggBucketSerializer(many=True)


class DownscaleEncoderAggBucketSerializer(serializers.Serializer):
    """
    serialize an encoder bucket - a plain single-field terms agg, so key
    is just the encoder string itself, unlike the channel bucket's
    multi_terms pair
    """

    key = serializers.CharField()
    doc_count = serializers.IntegerField()


class DownscaleEncoderAggsSerializer(serializers.Serializer):
    """serialize downscale encoder bucket aggregations"""

    doc_count_error_upper_bound = serializers.IntegerField()
    sum_other_doc_count = serializers.IntegerField()
    buckets = DownscaleEncoderAggBucketSerializer(many=True)
