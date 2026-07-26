"""
Functionality:
- handle channel subscriptions
- handle playlist subscriptions
"""

import json
import random
from datetime import datetime, timedelta
from typing import Callable

from appsettings.src.config import AppConfig
from channel.src.index import YoutubeChannel
from channel.src.remote_query import VideoQueryBuilder
from common.src.es_connect import ElasticWrap
from common.src.helper import get_channels, get_playlists
from common.src.urlparser import ParsedURLType, Parser
from download.src.extraction_queue import ExtractionQueue
from playlist.src.index import YoutubePlaylist
from video.src.constants import VideoTypeEnum
from video.src.index import YoutubeVideo

MIN_INTERVAL_HOURS = 1


def _is_due(item: dict, field: str, now_epoch: int) -> bool:
    """a subscription is due if it was never checked or its next
    check has passed"""
    return not item.get(field) or item[field] <= now_epoch


def _compute_next_check(
    frequency_hours: float, jitter_percent: float, now: datetime | None = None
) -> int:
    """compute a jittered next-check epoch, independent per call"""
    jitter_factor = 1 + random.uniform(-jitter_percent, jitter_percent) / 100
    interval_hours = max(frequency_hours * jitter_factor, MIN_INTERVAL_HOURS)
    next_check = (now or datetime.now()) + timedelta(hours=interval_hours)

    return int(next_check.timestamp())


def _advance_next_check(
    index_name: str,
    id_field: str,
    next_check_field: str,
    due_items: list[dict],
    config: dict,
) -> None:
    """bulk persist a freshly jittered next-check time for each due item"""
    if not due_items:
        return

    frequency_hours = config["subscriptions"].get("frequency_hours") or 24
    jitter_percent = config["subscriptions"].get("jitter_percent") or 0

    bulk_list = []
    for item in due_items:
        next_check = _compute_next_check(frequency_hours, jitter_percent)
        action = {"update": {"_id": item[id_field], "_index": index_name}}
        bulk_list.append(json.dumps(action))
        bulk_list.append(json.dumps({"doc": {next_check_field: next_check}}))

    bulk_list.append("\n")
    query_str = "\n".join(bulk_list)
    ElasticWrap("_bulk").post(query_str, ndjson=True)


def _run_subscription_scan(
    task,
    config: dict,
    all_items: list[dict],
    index_name: str,
    id_field: str,
    next_check_field: str,
    build_urls: Callable[[list[dict]], list[ParsedURLType]],
) -> int:
    """
    shared skeleton for channel/playlist subscription scans: filter to due
    items, let the caller build the type-specific queue entries, queue them,
    then advance each due item's next-check independently
    """
    if not all_items:
        return 0

    now_epoch = int(datetime.now().timestamp())
    due_items = [
        item
        for item in all_items
        if _is_due(item, next_check_field, now_epoch)
    ]
    if not due_items:
        return 0

    urls = build_urls(due_items)

    added = ExtractionQueue(task=task).add_to_queue(
        urls,
        auto_start=config["subscriptions"].get("auto_start", False),
        flat=config["subscriptions"].get("extract_flat", False),
    )

    _advance_next_check(
        index_name, id_field, next_check_field, due_items, config
    )

    return added


class ChannelSubscription:
    """scan subscribed channels to find missing videos to add to pending"""

    def __init__(self, task=None):
        self.config = AppConfig().config
        self.task = task

    def find_missing(self) -> int:
        """find missing videos from due channel subscriptions"""
        if self.task:
            self.task.send_progress(["Looking up channels."])

        all_channels = get_channels(
            subscribed_only=True,
            source=[
                "channel_id",
                "channel_overwrites",
                "channel_tabs",
                "channel_subscribed_next_check",
            ],
        )

        def build_urls(due_channels: list[dict]) -> list[ParsedURLType]:
            if self.task:
                self.task.send_progress(
                    [f"Scanning {len(due_channels)} channels"]
                )
            return self._process_channel_urls(due_channels)

        return _run_subscription_scan(
            self.task,
            self.config,
            all_channels,
            "ta_channel",
            "channel_id",
            "channel_subscribed_next_check",
            build_urls,
        )

    def _process_channel_urls(self, all_channels: list[dict]):
        """process channels, build queries"""

        all_channel_urls: list[ParsedURLType] = []

        for channel in all_channels:
            channel_tabs = channel["channel_tabs"]
            if not channel_tabs:
                continue

            enums = [getattr(VideoTypeEnum, i.upper()) for i in channel_tabs]
            queries = VideoQueryBuilder(
                config=self.config,
                channel_overwrites=channel.get("channel_overwrites", {}),
            ).build_queries(vid_types=enums)

            for vid_type, limit in queries:
                all_channel_urls.append(
                    ParsedURLType(
                        type="channel",
                        url=channel["channel_id"],
                        vid_type=vid_type,
                        limit=limit,
                    )
                )

        return all_channel_urls


class PlaylistSubscription:
    """scan subscribed playlists for videos to add to pending"""

    def __init__(self, task=None):
        self.config = AppConfig().config
        self.task = task

    def find_missing(self) -> int:
        """find missing from due playlist subscriptions"""
        all_playlists = get_playlists(
            subscribed_only=True,
            source=["playlist_id", "playlist_subscribed_next_check"],
        )

        def build_urls(due_playlists: list[dict]) -> list[ParsedURLType]:
            size_limit = self.config["subscriptions"]["playlist_size"]
            return [
                ParsedURLType(
                    type="playlist",
                    url=playlist["playlist_id"],
                    vid_type=VideoTypeEnum.UNKNOWN,
                    limit=size_limit,
                )
                for playlist in due_playlists
            ]

        return _run_subscription_scan(
            self.task,
            self.config,
            all_playlists,
            "ta_playlist",
            "playlist_id",
            "playlist_subscribed_next_check",
            build_urls,
        )


class SubscriptionScanner:
    """add missing videos to queue"""

    def __init__(self, task=False):
        self.task = task
        self.missing_videos = False
        self.auto_start = AppConfig().config["subscriptions"].get("auto_start")

    def scan(self):
        """scan channels and playlists"""
        if self.task:
            self.task.send_progress(["Rescanning channels and playlists."])

        added = 0
        added += ChannelSubscription(task=self.task).find_missing()
        if self.task and not self.task.is_stopped():
            added += PlaylistSubscription(task=self.task).find_missing()

        return added


class SubscriptionHandler:
    """subscribe to channels and playlists from url_str"""

    def __init__(self, url_str, task=False):
        self.url_str = url_str
        self.task = task
        self.to_subscribe = False

    def subscribe(self, expected_type=False):
        """subscribe to url_str items"""
        if self.task:
            self.task.send_progress(["Processing form content."])
        self.to_subscribe = Parser(self.url_str).parse()

        total = len(self.to_subscribe)
        for idx, item in enumerate(self.to_subscribe):
            if self.task:
                self._notify(idx, item, total)

            self.subscribe_type(item, expected_type=expected_type)

    def subscribe_type(self, item, expected_type):
        """process single item"""
        if item["type"] == "playlist":
            if expected_type and expected_type != "playlist":
                raise TypeError(
                    f"expected {expected_type} url but got {item.get('type')}"
                )

            playlist = YoutubePlaylist(item["url"])
            playlist.change_subscribe(new_subscribe_state=True)
            return

        if item["type"] == "video":
            # extract channel id from video
            video = YoutubeVideo(item["url"])
            video.get_from_youtube()
            video.process_youtube_meta()
            channel_id = video.channel_id
        elif item["type"] == "channel":
            channel_id = item["url"]
        else:
            raise ValueError("failed to subscribe to: " + item["url"])

        if expected_type and expected_type != "channel":
            raise TypeError(
                f"expected {expected_type} url but got {item.get('type')}"
            )

        self._subscribe(channel_id)

    def _subscribe(self, channel_id):
        """subscribe to channel"""
        YoutubeChannel(channel_id).change_subscribe(new_subscribe_state=True)

    def _notify(self, idx, item, total):
        """send notification message to redis"""
        subscribe_type = item["type"].title()
        message_lines = [
            f"Subscribe to {subscribe_type}",
            f"Progress: {idx + 1}/{total}",
        ]
        self.task.send_progress(message_lines, progress=(idx + 1) / total)
