"""appsettings erializers"""

# pylint: disable=abstract-method

from appsettings.src.manual import CHANNEL_ID_PATTERN, VIDEO_ID_PATTERN
from common.serializers import ValidateUnknownFieldsMixin
from common.src.helper import MIN_SLEEP_INTERVAL
from downscale.src.downscale import PRESET_CHOICES
from rest_framework import serializers


class BackupFileSerializer(serializers.Serializer):
    """serialize backup file"""

    filename = serializers.CharField()
    file_path = serializers.CharField()
    file_size = serializers.IntegerField()
    timestamp = serializers.CharField()
    reason = serializers.CharField()


class AppConfigSubSerializer(
    ValidateUnknownFieldsMixin, serializers.Serializer
):
    """serialize app config subscriptions"""

    channel_size = serializers.IntegerField(required=False, allow_null=True)
    live_channel_size = serializers.IntegerField(
        required=False, allow_null=True
    )
    shorts_channel_size = serializers.IntegerField(
        required=False, allow_null=True
    )
    playlist_size = serializers.IntegerField(required=False, allow_null=True)
    auto_start = serializers.BooleanField(required=False)
    extract_flat = serializers.BooleanField(required=False)
    frequency_hours = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    jitter_percent = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=100
    )


class AppConfigDownloadsSerializer(
    ValidateUnknownFieldsMixin, serializers.Serializer
):
    """serialize app config downloads config"""

    limit_speed = serializers.IntegerField(allow_null=True)
    sleep_interval = serializers.IntegerField(allow_null=True)
    autodelete_days = serializers.IntegerField(allow_null=True)
    format = serializers.CharField(allow_null=True)
    format_sort = serializers.CharField(allow_null=True)
    add_metadata = serializers.BooleanField()
    subtitle = serializers.CharField(allow_null=True)
    subtitle_source = serializers.ChoiceField(
        choices=["auto", "user"], allow_null=True
    )
    subtitle_index = serializers.BooleanField()
    comment_max = serializers.CharField(allow_null=True)
    comment_sort = serializers.ChoiceField(
        choices=["top", "new"], allow_null=True
    )
    cookie_import = serializers.BooleanField()
    pot_provider_url = serializers.CharField(allow_null=True)
    throttledratelimit = serializers.IntegerField(allow_null=True)
    extractor_lang = serializers.CharField(allow_null=True)
    integrate_ryd = serializers.BooleanField()
    integrate_sponsorblock = serializers.BooleanField()
    auto_rotate_exit_node = serializers.BooleanField()
    max_exit_node_rotates = serializers.IntegerField(min_value=1, max_value=25)

    def validate_sleep_interval(self, value):
        """0 and null both mean off, and both stay allowed

        Anything between is not a real setting: at 1 the randomised
        window collapses to always zero, and 2 to 4 are too narrow to
        be worth the option. Rejecting 0 outright would break stored
        configs already using it to disable pacing.
        """
        if value and value < MIN_SLEEP_INTERVAL:
            raise serializers.ValidationError(
                f"use 0 or leave empty to disable pacing, "
                f"or {MIN_SLEEP_INTERVAL} and above to enable it"
            )

        return value


class AppConfigAppSerializer(
    ValidateUnknownFieldsMixin, serializers.Serializer
):
    """serialize app config"""

    enable_snapshot = serializers.BooleanField()
    enable_cast = serializers.BooleanField()
    downscale_max_concurrent = serializers.IntegerField(
        allow_null=True, min_value=0
    )
    downscale_encoder = serializers.ChoiceField(
        choices=[
            "h264",
            "h264_vaapi",
            "h265",
            "h265_vaapi",
            "av1",
            "av1_vaapi",
        ]
    )
    downscale_crf = serializers.IntegerField(
        allow_null=True, min_value=0, max_value=63
    )
    downscale_preset = serializers.ChoiceField(
        choices=PRESET_CHOICES, allow_null=True
    )
    log_retention_days = serializers.IntegerField(min_value=1, max_value=365)


class AppConfigSerializer(ValidateUnknownFieldsMixin, serializers.Serializer):
    """serialize appconfig"""

    subscriptions = AppConfigSubSerializer(required=False)
    downloads = AppConfigDownloadsSerializer(required=False)
    application = AppConfigAppSerializer(required=False)


class CookieValidationSerializer(serializers.Serializer):
    """serialize cookie validation response"""

    cookie_enabled = serializers.BooleanField()
    status = serializers.BooleanField(required=False)
    validated = serializers.IntegerField(required=False)
    validated_str = serializers.CharField(required=False)


class CookieUpdateSerializer(serializers.Serializer):
    """serialize cookie to update"""

    cookie = serializers.CharField()


class RescanFileSystemConfig(serializers.Serializer):
    """serialize rescan filesystem config"""

    ignore_error = serializers.BooleanField()
    prefer_local = serializers.BooleanField()


class ManualImportConfig(serializers.Serializer):
    """serialize for manual import task"""

    ignore_error = serializers.BooleanField()
    prefer_local = serializers.BooleanField()


class ImportFileSerializer(serializers.Serializer):
    """serialize a file staged in the import folder"""

    filename = serializers.CharField()
    size = serializers.IntegerField()
    category = serializers.CharField()
    video_id = serializers.CharField(allow_null=True)


class ImportFileUploadSerializer(serializers.Serializer):
    """serialize import folder upload"""

    files = serializers.ListField(child=serializers.FileField())


class ImportMetadataSerializer(serializers.Serializer):
    """serialize a hand written info.json for manual import

    the fields the import path actually reads - YoutubeVideo
    .process_youtube_meta and YoutubeChannel._video_fallback - not the
    whole yt-dlp schema
    """

    video_id = serializers.RegexField(f"^{VIDEO_ID_PATTERN}$")
    # see CHANNEL_ID_PATTERN: this one becomes a directory name
    channel_id = serializers.RegexField(f"^{CHANNEL_ID_PATTERN}$")
    channel_name = serializers.CharField(max_length=255)
    title = serializers.CharField(max_length=500)
    upload_date = serializers.DateField()
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=50000
    )
    thumbnail = serializers.URLField(required=False, allow_blank=True)
    view_count = serializers.IntegerField(required=False, min_value=0)
    like_count = serializers.IntegerField(required=False, min_value=0)


class SnapshotItemSerializer(serializers.Serializer):
    """serialize snapshot response"""

    id = serializers.CharField()
    state = serializers.CharField()
    es_version = serializers.CharField()
    start_date = serializers.CharField()
    end_date = serializers.CharField()
    end_stamp = serializers.IntegerField()
    duration_s = serializers.IntegerField()


class SnapshotListSerializer(serializers.Serializer):
    """serialize snapshot list response"""

    next_exec = serializers.IntegerField()
    next_exec_str = serializers.CharField()
    expire_after = serializers.CharField()
    snapshots = SnapshotItemSerializer(many=True)


class SnapshotCreateResponseSerializer(serializers.Serializer):
    """serialize new snapshot creating response"""

    snapshot_name = serializers.CharField()


class SnapshotRestoreResponseSerializer(serializers.Serializer):
    """serialize snapshot restore response"""

    accepted = serializers.BooleanField()


class TokenResponseSerializer(serializers.Serializer):
    """serialize token response"""

    token = serializers.CharField(allow_null=True)


class TailscaleNodeSerializer(serializers.Serializer):
    """serialize a selectable tailscale exit node"""

    node_id = serializers.CharField()
    hostname = serializers.CharField()
    country = serializers.CharField(allow_null=True)
    city = serializers.CharField(allow_null=True)
    online = serializers.BooleanField()
    is_mullvad = serializers.BooleanField()


class TailscaleStateSerializer(serializers.Serializer):
    """serialize exit node state

    available false is the whole when-present story: there is no
    tailscaled socket in this container, so the panel hides itself
    """

    available = serializers.BooleanField()
    routes_all_traffic = serializers.BooleanField()
    current = TailscaleNodeSerializer(allow_null=True)
    nodes = TailscaleNodeSerializer(many=True)


class TailscaleUpdateSerializer(serializers.Serializer):
    """serialize an exit node change

    node_id belongs to set, rotate and clear take nothing
    """

    action = serializers.ChoiceField(choices=["set", "rotate", "clear"])
    node_id = serializers.CharField(required=False)


class TailscaleEgressSerializer(serializers.Serializer):
    """serialize the address the outside world sees

    is_mullvad null means the check fell back to a plain ip echo, which
    cannot tell whether the traffic left through an exit node
    """

    ip = serializers.CharField(allow_null=True)
    country = serializers.CharField(allow_null=True)
    city = serializers.CharField(allow_null=True)
    organization = serializers.CharField(allow_null=True)
    is_mullvad = serializers.BooleanField(allow_null=True)
    exit_hostname = serializers.CharField(allow_null=True)
