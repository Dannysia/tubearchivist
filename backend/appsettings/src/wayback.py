"""
Functionality:
- recover metadata for a video YouTube has removed from the Wayback Machine
- fills the generated info.json a manual import falls back to
"""

from datetime import datetime

from appsettings.src.manual import is_safe_channel_id, is_video_id
from download.src.yt_dlp_base import YtWrap

# yt-dlp's web.archive:youtube extractor. the prefix form lets it pick
# the capture itself, so there is no snapshot timestamp to keep in step
# with the video id
ARCHIVE_PREFIX = "ytarchive:"

# the caps ImportMetadataSerializer puts on these, applied here so what
# comes back is always postable straight back to that endpoint
MAX_DESCRIPTION = 50000
MAX_TITLE = 500
MAX_CHANNEL_NAME = 255

# a capture of the video's own watch page carries at least one of these.
# The wayback machine also holds captures of youtube's redirect and
# "video unavailable" pages under the same watch url, and for a video
# removed before its first capture those are all there is. They come
# back with a page title and nothing else - "Broadcast Yourself." and
# "YouTube" both measured live - so a title alone is not a hit. Taking
# one would fill the form with a page title and index it as the video's
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
        # the wayback video store and the page captures are indexed
        # separately, and a watch page is regularly archived with no
        # playable video behind it. that page is all this wants, so the
        # missing formats must not read as the whole lookup failing
        "ignore_no_formats_error": True,
        # someone is sitting in front of this waiting on it, so keep it
        # bounded. the cdx api is flaky enough that a retry or two still
        # earns its place
        "socket_timeout": 15,
        "retries": 2,
        "extractor_retries": 2,
    }

    def __init__(self, video_id: str):
        self.video_id = video_id

    def get(self) -> dict | None:
        """archived metadata, None when no capture had any"""
        # the view checks this too, so a caller cannot reach yt-dlp with
        # an unvalidated id by either route
        if not is_video_id(self.video_id):
            raise ValueError(f"{self.video_id}: not an 11 character video id")

        # no config on purpose: this request goes to web.archive.org, and
        # the youtube cookie and pot token have no business being sent
        # anywhere but youtube
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

        fulltitle is the title as the extractor returned it, before
        YoutubeDL substitutes a generic "<extractor> video #<id>" for a
        missing one, so an empty one means no capture was readable at
        all. A title on its own is not enough though - see
        IDENTITY_FIELDS for the pages that also answer on this url.
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
            # channel_id becomes a directory name under the media root on
            # import, so an id that could not be one is dropped rather
            # than handed on for the user to paste into the form
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

        the singular key is only promoted out of the list when there are
        formats to go with it, and a page-only capture has none
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
