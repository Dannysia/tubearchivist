"""channel serializers"""

# pylint: disable=abstract-method

from channel.src.constants import ChannelSortEnum
from common.serializers import PaginationSerializer, ValidateUnknownFieldsMixin
from downscale.serializers import DownscaleBulkResultItemSerializer
from rest_framework import serializers
from video.src.constants import OrderEnum, VideoTypeEnum


class ChannelOverwriteSerializer(
    ValidateUnknownFieldsMixin, serializers.Serializer
):
    """serialize channel overwrites"""

    download_format = serializers.CharField(required=False, allow_null=True)
    autodelete_days = serializers.IntegerField(required=False, allow_null=True)
    index_playlists = serializers.BooleanField(required=False, allow_null=True)
    integrate_sponsorblock = serializers.BooleanField(
        required=False, allow_null=True
    )
    subscriptions_channel_size = serializers.IntegerField(
        required=False, allow_null=True
    )
    subscriptions_live_channel_size = serializers.IntegerField(
        required=False, allow_null=True
    )
    subscriptions_shorts_channel_size = serializers.IntegerField(
        required=False, allow_null=True
    )


class ChannelListStatSerializer(serializers.Serializer):
    """serialize the video stats of a channel list item"""

    doc_count = serializers.IntegerField()
    media_size = serializers.IntegerField()
    duration = serializers.IntegerField()
    duration_str = serializers.CharField()
    watch_progress = serializers.FloatField()
    last_download = serializers.CharField(allow_null=True)
    last_published = serializers.CharField(allow_null=True)


class ChannelSerializer(serializers.Serializer):
    """serialize channel"""

    channel_id = serializers.CharField()
    channel_active = serializers.BooleanField()
    channel_banner_url = serializers.CharField(allow_null=True, required=False)
    channel_thumb_url = serializers.CharField(allow_null=True, required=False)
    channel_tvart_url = serializers.CharField(allow_null=True, required=False)
    channel_description = serializers.CharField(
        allow_null=True, required=False
    )
    channel_last_refresh = serializers.CharField()
    channel_name = serializers.CharField()
    channel_overwrites = ChannelOverwriteSerializer(required=False)
    channel_subs = serializers.IntegerField()
    channel_subscribed = serializers.BooleanField()
    channel_subscribed_next_check = serializers.CharField(
        allow_null=True, required=False
    )
    channel_tags = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    channel_tabs = serializers.ListField(
        child=serializers.ChoiceField(VideoTypeEnum.values_known())
    )
    channel_stats = ChannelListStatSerializer(required=False)
    _index = serializers.CharField(required=False)
    _score = serializers.IntegerField(required=False)


class ChannelListSerializer(serializers.Serializer):
    """serialize channel list"""

    data = ChannelSerializer(many=True)
    paginate = PaginationSerializer()


class ChannelListQuerySerializer(serializers.Serializer):
    """serialize list query"""

    filter = serializers.ChoiceField(
        choices=["subscribed", "unsubscribed"], required=False
    )
    sort = serializers.ChoiceField(
        choices=ChannelSortEnum.names(), required=False
    )
    order = serializers.ChoiceField(choices=OrderEnum.values(), required=False)
    page = serializers.IntegerField(required=False)


class ChannelUpdateSerializer(serializers.Serializer):
    """update channel"""

    channel_subscribed = serializers.BooleanField(required=False)
    channel_overwrites = ChannelOverwriteSerializer(required=False)


class ChannelAggBucketSerializer(serializers.Serializer):
    """serialize channel agg bucket"""

    value = serializers.IntegerField()
    value_str = serializers.CharField(required=False)


class ChannelAggStatSerializer(serializers.Serializer):
    """serialize a channel agg bucket with size and duration"""

    doc_count = serializers.IntegerField()
    media_size = serializers.IntegerField()
    duration = serializers.IntegerField()
    duration_str = serializers.CharField()


class ChannelAggTypeSerializer(serializers.Serializer):
    """serialize channel aggregation by vid_type"""

    videos = ChannelAggStatSerializer()
    shorts = ChannelAggStatSerializer()
    streams = ChannelAggStatSerializer()
    unknown = ChannelAggStatSerializer()


class ChannelAggWatchSerializer(serializers.Serializer):
    """serialize channel watch progress"""

    watched = ChannelAggStatSerializer()
    unwatched = ChannelAggStatSerializer()
    progress = serializers.FloatField()


class ChannelAggActiveSerializer(serializers.Serializer):
    """serialize channel availability"""

    active = serializers.IntegerField()
    inactive = serializers.IntegerField()


class ChannelAggDownscaleSerializer(serializers.Serializer):
    """serialize channel downscale totals"""

    doc_count = serializers.IntegerField()
    original_size = serializers.IntegerField()
    new_size = serializers.IntegerField()
    saved = serializers.IntegerField()


class ChannelAggDateRangeSerializer(serializers.Serializer):
    """serialize channel date range"""

    published_first = serializers.CharField(allow_null=True)
    published_last = serializers.CharField(allow_null=True)
    downloaded_first = serializers.CharField(allow_null=True)
    downloaded_last = serializers.CharField(allow_null=True)


class ChannelAggSerializer(serializers.Serializer):
    """serialize channel aggregation"""

    total_items = ChannelAggBucketSerializer()
    total_size = ChannelAggBucketSerializer()
    total_duration = ChannelAggBucketSerializer()
    by_type = ChannelAggTypeSerializer()
    watch_progress = ChannelAggWatchSerializer()
    availability = ChannelAggActiveSerializer()
    downscale = ChannelAggDownscaleSerializer()
    date_range = ChannelAggDateRangeSerializer()


class ChannelNavSerializer(serializers.Serializer):
    """serialize channel navigation"""

    has_pending = serializers.BooleanField()
    has_ignored = serializers.BooleanField()
    has_playlists = serializers.BooleanField()
    has_videos = serializers.BooleanField()
    has_streams = serializers.BooleanField()
    has_shorts = serializers.BooleanField()


class ChannelSearchQuerySerializer(serializers.Serializer):
    """serialize query parameters for searching"""

    q = serializers.CharField()


class ChannelDownscaleSerializer(serializers.Serializer):
    """serialize channel batch downscale response"""

    queued = serializers.ListField(child=serializers.CharField())
    skipped = DownscaleBulkResultItemSerializer(many=True)


class ChannelVideoDeleteQuerySerializer(serializers.Serializer):
    """serialize query parameters for deleting videos by type"""

    # required and with no default on purpose: this endpoint is a
    # narrower delete than DELETE /api/channel/<id>/, and a missing or
    # misspelled type has to fail rather than fall back to everything
    vid_type = serializers.ChoiceField(
        choices=VideoTypeEnum.values_known(), required=True
    )
    # add the deleted videos to the ignore list so a subscribed channel
    # does not just download them again on the next scan
    ignore = serializers.BooleanField(required=False, default=False)
