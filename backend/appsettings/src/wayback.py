"""recover metadata for a removed video from the Wayback Machine"""

from datetime import datetime

from appsettings.src.manual import is_safe_channel_id, is_video_id
from download.src.yt_dlp_base import YtWrap

# yt-dlp's web.archive:youtube extractor; the prefix form lets it pick
# the capture, so there is no snapshot timestamp to keep in step
ARCHIVE_PREFIX = "ytarchive:"

# the caps ImportMetadataSerializer puts on these, so a result posts back
MAX_DESCRIPTION = 50000
MAX_TITLE = 500
MAX_CHANNEL_NAME = 255

# a capture of the video's own watch page carries at least one of these.
# The wayback machine also holds captures of youtube's redirect and
# "video unavailable" pages under the same watch url, and those come
# back with a page title and nothing else, so a title is not a hit.
IDENTITY_FIELDS = (
    "channel_id",
    "uploader",
    "channel",
    "upload_date",
    "release_date",
    "timestamp",
)


class WaybackMetadata:
    """metadata for one video id from the Internet Archive"""

    OBS = {
        # metadata only, the media file is already in the import folder
        "skip_download": True,
        "noplaylist": True,
        # a watch page is regularly archived with no playable video
        # behind it, and that page is all this wants
        "ignore_no_formats_error": True,
        # someone is waiting on this, so keep it bounded; the cdx api
        # is flaky enough that a retry or two still earns its place
        "socket_timeout": 15,
        "retries": 2,
        "extractor_retries": 2,
    }

    def __init__(self, video_id: str):
        self.video_id = video_id

    def get(self) -> dict | None:
        """archived metadata, None when no capture had any"""
        if not is_video_id(self.video_id):
            raise ValueError(f"{self.video_id}: not an 11 character video id")

        # no config on purpose: the youtube cookie and pot token must
        # not be sent to web.archive.org
        response, error = YtWrap(self.OBS).extract(
            f"{ARCHIVE_PREFIX}{self.video_id}"
        )
        if error:
            raise ConnectionError(error)

        if not response:
            return None

        return self._build(response)

    def _build(self, response: dict) -> dict | None:
        """map a yt-dlp response onto the import metadata fields

        fulltitle is the title before YoutubeDL substitutes a generic
        "<extractor> video #<id>" for a missing one, so an empty one
        means no capture was readable at all.
        """
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
            # becomes a directory name under the media root on import,
            # so an unusable id is dropped rather than handed on
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
        """yt-dlp's YYYYMMDD as the iso date a date input takes"""
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
        """best archived thumbnail url

        yt-dlp promotes the singular key out of the list only when there
        are formats, and a page-only capture has none
        """
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
