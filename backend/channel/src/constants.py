import enum

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
        return [i.value for i in cls]

    @classmethod
    def names(cls) -> list[str]:
        return [i.name.lower() for i in cls]

    @classmethod
    def from_name(cls, name: str) -> "ChannelSortEnum":
        if not hasattr(cls, name.upper()):
            raise ValueError(f"'{name}' not in ChannelSortEnum")

        return getattr(cls, name.upper())

    @property
    def is_stat(self) -> bool:
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
