"""channel constants"""

import enum

# every key channel_overwrites accepts. Both the serializer that
# validates an incoming update and YoutubeChannel.set_overwrites, which
# refuses anything it does not recognise, build from this. They used to
# hold the list separately, so a field added to the serializer alone
# validated cleanly and then died in set_overwrites with a ValueError -
# a 500 with nothing in the log, not a 400 saying what was wrong.
OVERWRITE_KEYS = [
    "download_format",
    "downscale_target_height",
    "index_playlists",
    "integrate_sponsorblock",
    "subscriptions_channel_size",
    "subscriptions_live_channel_size",
    "subscriptions_shorts_channel_size",
]


class ChannelSortEnum(enum.Enum):
    """all channel list sort options

    values are either a field on the channel doc or, for the stat sorts, a
    key of the per channel video aggregation in ChannelListAggs
    """

    NAME = "channel_name.keyword"
    SUBSCRIBERS = "channel_subs"
    LAST_REFRESH = "channel_last_refresh"
    VIDEOS = "doc_count"
    MEDIA_SIZE = "media_size"
    DURATION = "duration"
    LAST_DOWNLOAD = "last_download"
    LAST_PUBLISHED = "last_published"
    WATCH_PROGRESS = "watch_progress"

    @classmethod
    def values(cls) -> list[str]:
        """value list"""
        return [i.value for i in cls]

    @classmethod
    def names(cls) -> list[str]:
        """name list"""
        return [i.name.lower() for i in cls]

    @classmethod
    def from_name(cls, name: str) -> "ChannelSortEnum":
        """get member by api name"""
        if not hasattr(cls, name.upper()):
            raise ValueError(f"'{name}' not in ChannelSortEnum")

        return getattr(cls, name.upper())

    @property
    def is_stat(self) -> bool:
        """sorts not backed by a field on the channel doc"""
        return self in STAT_SORTS


STAT_SORTS = frozenset(
    {
        ChannelSortEnum.VIDEOS,
        ChannelSortEnum.MEDIA_SIZE,
        ChannelSortEnum.DURATION,
        ChannelSortEnum.LAST_DOWNLOAD,
        ChannelSortEnum.LAST_PUBLISHED,
        ChannelSortEnum.WATCH_PROGRESS,
    }
)
