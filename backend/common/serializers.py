"""common serializers"""

# pylint: disable=abstract-method

from rest_framework import serializers


class ValidateUnknownFieldsMixin:
    """
    Mixin to validate and reject unknown fields in a serializer.
    """

    def to_internal_value(self, data):
        """check expected keys"""
        allowed_fields = set(self.fields.keys())
        input_fields = set(data.keys())

        # Find unknown fields
        unknown_fields = input_fields - allowed_fields
        if unknown_fields:
            raise serializers.ValidationError(
                {"error": f"Unknown fields: {', '.join(unknown_fields)}"}
            )

        return super().to_internal_value(data)


class ErrorResponseSerializer(serializers.Serializer):
    """error message"""

    error = serializers.CharField()


class PaginationSerializer(serializers.Serializer):
    """serialize paginate response"""

    page_size = serializers.IntegerField()
    page_from = serializers.IntegerField()
    prev_pages = serializers.ListField(
        child=serializers.IntegerField(), allow_null=True
    )
    current_page = serializers.IntegerField()
    max_hits = serializers.BooleanField()
    params = serializers.CharField()
    last_page = serializers.IntegerField()
    next_pages = serializers.ListField(
        child=serializers.IntegerField(), allow_null=True
    )
    total_hits = serializers.IntegerField()


class ResolutionBucketSerializer(serializers.Serializer):
    """serialize one tier of the resolution breakdown"""

    # a rung of the downscale ladder as a string, "1440", or one of the
    # two catch alls, "below" and "unknown"
    key = serializers.CharField()
    doc_count = serializers.IntegerField()
    media_size = serializers.IntegerField()
    duration = serializers.IntegerField()
    duration_str = serializers.CharField()


class AsyncTaskResponseSerializer(serializers.Serializer):
    """serialize new async task"""

    message = serializers.CharField(required=False)
    task_id = serializers.CharField()
    status = serializers.CharField(required=False)
    filename = serializers.CharField(required=False)


class NotificationSerializer(serializers.Serializer):
    """serialize notification messages"""

    id = serializers.CharField()
    title = serializers.CharField()
    group = serializers.CharField()
    api_start = serializers.BooleanField()
    api_stop = serializers.BooleanField()
    level = serializers.ChoiceField(choices=["info", "error"])
    messages = serializers.ListField(child=serializers.CharField())
    progress = serializers.FloatField(required=False)
    command = serializers.ChoiceField(choices=["STOP", "KILL"], required=False)


class NotificationQueryFilterSerializer(serializers.Serializer):
    """serialize notification query filter"""

    filter = serializers.ChoiceField(
        choices=["download", "settings", "channel", "downscale"],
        required=False,
    )


class PingUpdateSerializer(serializers.Serializer):
    """serialize update notification"""

    status = serializers.BooleanField()
    version = serializers.CharField()
    is_breaking = serializers.BooleanField()


class PingSerializer(serializers.Serializer):
    """serialize ping response"""

    response = serializers.ChoiceField(choices=["pong"])
    user = serializers.IntegerField()
    version = serializers.CharField()
    # empty for an image built without the build args
    build_sha = serializers.CharField(allow_blank=True)
    build_date = serializers.CharField(allow_blank=True)
    ta_update = PingUpdateSerializer(required=False)


class WatchedDataSerializer(serializers.Serializer):
    """mark as watched serializer"""

    id = serializers.CharField()
    is_watched = serializers.BooleanField()


class RefreshQuerySerializer(serializers.Serializer):
    """refresh query filtering"""

    type = serializers.ChoiceField(
        choices=["video", "channel", "playlist"], required=False
    )
    id = serializers.CharField(required=False)


class RefreshResponseSerializer(serializers.Serializer):
    """serialize refresh response"""

    id = serializers.CharField(allow_null=True)
    state = serializers.ChoiceField(
        choices=["running", "in_queue", "empty", "not_in_queue", "processing"]
    )
    total_queued = serializers.IntegerField()
    queue_type = serializers.ChoiceField(
        choices=["all", "video", "channel", "playlist"]
    )
    queue_position = serializers.IntegerField(allow_null=True)


class RefreshAddQuerySerializer(serializers.Serializer):
    """serialize add to refresh queue"""

    extract_videos = serializers.BooleanField(required=False)


class RefreshAddDataSerializer(serializers.Serializer):
    """add to refresh queue serializer"""

    video = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    channel = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    playlist = serializers.ListField(
        child=serializers.CharField(), required=False
    )


class LogEntrySerializer(serializers.Serializer):
    """serialize a single log entry"""

    id = serializers.CharField()
    timestamp = serializers.IntegerField()
    source = serializers.CharField()
    level = serializers.CharField()
    message = serializers.CharField()
    event = serializers.CharField(required=False)
    task_id = serializers.CharField(required=False)
    task_name = serializers.CharField(required=False)
    task_title = serializers.CharField(required=False)
    group = serializers.CharField(required=False)


class LogTaskOptionSerializer(serializers.Serializer):
    """serialize one entry of the task filter dropdown"""

    task_name = serializers.CharField()
    task_title = serializers.CharField()


class LogListSerializer(serializers.Serializer):
    """serialize log list response"""

    data = LogEntrySerializer(many=True)
    paginate = PaginationSerializer()
    tasks = LogTaskOptionSerializer(many=True)


class LogQueryFilterSerializer(serializers.Serializer):
    """serialize log list query filters"""

    source = serializers.ChoiceField(
        choices=["notification", "application"], required=False
    )
    level = serializers.ChoiceField(choices=["info", "error"], required=False)
    task_name = serializers.CharField(required=False)
    q = serializers.CharField(required=False)
    page = serializers.IntegerField(required=False)


class LogDeleteQuerySerializer(serializers.Serializer):
    """serialize log delete query"""

    source = serializers.ChoiceField(
        choices=["notification", "application"], required=False
    )


class LogDeleteResultSerializer(serializers.Serializer):
    """serialize log delete result"""

    deleted = serializers.IntegerField()
