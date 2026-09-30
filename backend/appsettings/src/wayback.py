"""recover metadata for a removed video from the Wayback Machine"""

from datetime import datetime

from appsettings.src.manual import is_safe_channel_id, is_video_id
from download.src.yt_dlp_base import YtWrap

# yt-dlp's web.archive:youtube extractor
ARCHIVE_PREFIX = "ytarchive:"

MAX_DESCRIPTION = 50000
MAX_TITLE = 500
MAX_CHANNEL_NAME = 255

# a capture of youtube's redirect or unavailable page has only a title
IDENTITY_FIELDS = (
    "channel_id",
    "uploader",
    "channel",
    "upload_date",
    "release_date",
    "timestamp",
)


class WaybackMetadata:
    OBS = {
        "skip_download": True,
        "noplaylist": True,
        "ignore_no_formats_error": True,
        "socket_timeout": 15,
        "retries": 2,
        "extractor_retries": 2,
    }

    def __init__(self, video_id: str):
        self.video_id = video_id

    def get(self) -> dict | None:
        if not is_video_id(self.video_id):
            raise ValueError(f"{self.video_id}: not an 11 character video id")

        # no config on purpose, it carries the youtube cookie
        response, error = YtWrap(self.OBS).extract(
            f"{ARCHIVE_PREFIX}{self.video_id}"
        )
        if error:
            raise ConnectionError(error)

        if not response:
            return None

        return self._build(response)

    def _build(self, response: dict) -> dict | None:
        """fulltitle is empty when no capture was readable"""
        title = response.get("fulltitle")
        if not title:
            return None

        if not any(response.get(field) for field in IDENTITY_FIELDS):
            print(
                f"wayback: {self.video_id}: the only captures are of a "
                f"page titled {title!r}, not of the video"
            )
            return None

        channel_id = response.get("channel_id")

        return {
            "video_id": self.video_id,
            "title": title[:MAX_TITLE],
            "channel_id": channel_id if is_safe_channel_id(channel_id) else "",
            "channel_name": (
                response.get("uploader") or response.get("channel") or ""
            )[:MAX_CHANNEL_NAME],
            "upload_date": self._upload_date(response),
            "description": (response.get("description") or "")[
                :MAX_DESCRIPTION
            ],
            "thumbnail": self._thumbnail(response),
            "view_count": response.get("view_count"),
            "like_count": response.get("like_count"),
        }

    @staticmethod
    def _upload_date(response: dict) -> str:
        raw = response.get("upload_date") or response.get("release_date")
        if not raw:
            return ""

        try:
            return datetime.strptime(raw, "%Y%m%d").date().isoformat()
        except (TypeError, ValueError):
            print(f"wayback: unreadable upload_date {raw}")
            return ""

    @staticmethod
    def _thumbnail(response: dict) -> str:
        """yt-dlp sets the singular thumbnail only when there are formats"""
        thumbnail = response.get("thumbnail")
        if thumbnail:
            return thumbnail

        # yt-dlp sorts these worst to best
        thumbnails = response.get("thumbnails") or []
        for candidate in reversed(thumbnails):
            url = (candidate or {}).get("url")
            if url:
                return url

        return ""
