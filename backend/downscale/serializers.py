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
    page = serializers.IntegerField(required=False)


class DownscaleBulkActionSerializer(serializers.Serializer):
    """serialize bulk accept/reject/retry request"""

    ids = serializers.ListField(child=serializers.CharField())
    action = serializers.ChoiceField(choices=["accept", "reject", "retry"])


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
