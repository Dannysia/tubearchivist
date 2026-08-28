"""
functionality:
- get metadata from youtube for a channel
- index and update in es
"""

import json
import os
from datetime import datetime

from channel.src.remote_query import get_last_channel_videos
from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap, IndexPaginate
from common.src.helper import countdown_sleep
from common.src.index_generic import YouTubeItem
from download.src.thumbnails import ThumbManager
from download.src.yt_dlp_base import YtWrap
from video.src.constants import VideoTypeEnum


class YoutubeChannel(YouTubeItem):
    """represents a single youtube channel"""

    es_path = False
    index_name = "ta_channel"
    yt_base = "https://www.youtube.com/channel/"
    yt_obs = {
        "playlist_items": "0,0",
        "skip_download": True,
    }

    def __init__(self, youtube_id, task=False):
        super().__init__(youtube_id)
        self.all_playlists = False
        self.task = task

    def build_json(self, upload=False, fallback=False):
        """get from es or from youtube"""
        self.get_from_es()
        if self.json_data:
            return

        self.get_from_youtube()
        if not self.youtube_meta and fallback:
            self._video_fallback(fallback)
        else:
            if not self.youtube_meta:
                message = f"{self.youtube_id}: Failed to get metadata"
                raise ValueError(message)

            self.process_youtube_meta()
            self.get_channel_art()

        if upload:
            self.upload_to_es()

    def process_youtube_meta(self):
        """extract relevant fields"""
        self.youtube_meta["thumbnails"].reverse()
        channel_name = self.youtube_meta["uploader"] or self.youtube_meta["id"]
        description = self.youtube_meta.get("description") or None
        self.json_data = {
            "channel_active": True,
            "channel_description": description,
            "channel_id": self.youtube_id,
            "channel_last_refresh": int(datetime.now().timestamp()),
            "channel_name": channel_name,
            "channel_subs": self.youtube_meta.get("channel_follower_count")
            or 0,
            "channel_subscribed": False,
            "channel_tags": self.youtube_meta.get("tags", []),
            "channel_tabs": self.get_channel_tabs(),
        }

        self._get_thumb_art()
        self._get_tv_art()
        self._get_banner_art()

    def _get_thumb_art(self) -> None:
        """extract thumb art"""
        for i in self.youtube_meta["thumbnails"]:
            if not i.get("width"):
                continue
            if i.get("width") == i.get("height"):
                self.json_data["channel_thumb_url"] = i["url"]
                return

    def _get_tv_art(self) -> None:
        """extract tv artwork"""
        for i in self.youtube_meta["thumbnails"]:
            if i.get("id") == "banner_uncropped":
                self.json_data["channel_tvart_url"] = i["url"]
                return
        for i in self.youtube_meta["thumbnails"]:
            if not i.get("width"):
                continue
            if i["width"] // i["height"] < 2 and not i["width"] == i["height"]:
                self.json_data["channel_tvart_url"] = i["url"]
                return

        return

    def _get_banner_art(self) -> None:
        """extract banner artwork"""
        for i in self.youtube_meta["thumbnails"]:
            if not i.get("width"):
                continue
            if i["width"] // i["height"] > 5:
                self.json_data["channel_banner_url"] = i["url"]
                return

    def get_channel_tabs(self) -> list[str]:
        """get channel tabs"""
        tabs = VideoTypeEnum.values_known()
        config_cp = self.config.copy()
        tabs = []
        for query_filter in VideoTypeEnum:
            if query_filter == VideoTypeEnum.UNKNOWN:
                continue

            videos = get_last_channel_videos(
                channel_id=self.youtube_id,
                config=config_cp,
                limit=1,
                query_filter=query_filter,
            )
            if videos:
                tabs.append(query_filter.value)

        return tabs

    def _video_fallback(self, fallback):
        """use video metadata as fallback"""
        print(f"{self.youtube_id}: fallback to video metadata")
        self.json_data = {
            "channel_active": False,
            "channel_last_refresh": int(datetime.now().timestamp()),
            "channel_subs": fallback.get("channel_follower_count") or 0,
            "channel_name": fallback["uploader"],
            "channel_id": self.youtube_id,
            "channel_subscribed": False,
            "channel_tags": [],
        }

    def get_channel_art(self):
        """download channel art for new channels"""
        urls = (
            self.json_data.get("channel_thumb_url"),
            self.json_data.get("channel_banner_url"),
            self.json_data.get("channel_tvart_url"),
        )
        ThumbManager(self.youtube_id, item_type="channel").download(urls)

    def sync_to_videos(self):
        """sync new channel_dict to all videos of channel"""
        data = {
            "query": {
                "term": {"channel.channel_id": {"value": self.youtube_id}},
            },
            "script": {
                "lang": "painless",
                "params": {"channel": self.json_data},
                "source": "ctx._source.channel = params.channel",
            },
        }
        update_path = "ta_video/_update_by_query"
        response, status_code = ElasticWrap(update_path).post(data)
        if status_code not in [200, 201]:
            print(f"sync to videos failed with status code {status_code}")
            print(response)

    def change_subscribe(self, new_subscribe_state: bool):
        """change subscribe status"""
        if not self.json_data:
            self.build_json()

        self.json_data["channel_subscribed"] = new_subscribe_state
        if new_subscribe_state:
            self.json_data["channel_subscribed_next_check"] = int(
                datetime.now().timestamp()
            )

        self.upload_to_es()
        self.sync_to_videos()
        return self.json_data

    def delete_channel(self):
        """delete channel and all videos"""
        print(f"{self.youtube_id}: delete channel")
        self.get_from_es()
        if not self.json_data:
            raise FileNotFoundError

        ChannelDelete(json_data=self.json_data).delete()

    def index_channel_playlists(self):
        """add all playlists of channel to index"""
        print(f"{self.youtube_id}: index all playlists")
        self.get_from_es()
        channel_name = self.json_data["channel_name"]
        self.task.send_progress([f"{channel_name}: Looking for Playlists"])
        self.get_all_playlists()
        if not self.all_playlists:
            print(f"{self.youtube_id}: no playlists found.")
            return

        total = len(self.all_playlists)
        for idx, playlist in enumerate(self.all_playlists):
            if self.task:
                self._notify_single_playlist(idx, total)

            self._index_single_playlist(playlist)
            print("add playlist: " + playlist[1])
            if not self._wait_for_next_playlist(idx, total):
                break

    def _wait_for_next_playlist(self, idx: int, total: int) -> bool:
        """pace the next youtube request, when there is one to pace

        idx counts from zero here, so the last pass is total - 1. There
        is nothing to pace after it: index_channel_playlists is the
        whole body of the index_playlists task, so a wait there would
        only delay the task finishing.
        """
        if idx + 1 == total:
            return True

        if not self.task:
            return countdown_sleep(self.config, self.task)

        return countdown_sleep(
            self.config,
            self.task,
            lambda msg: self._notify_single_playlist(idx, total, waiting=msg),
            label="next playlist",
        )

    def get_all_playlists(self):
        """get all playlists owned by this channel"""
        url = (
            f"https://www.youtube.com/channel/{self.youtube_id}"
            + "/playlists?view=1&sort=dd&shelf_id=0"
        )
        obs = {"skip_download": True, "extract_flat": True}
        playlists, _ = YtWrap(obs, self.config, task=self.task).extract(url)
        if not playlists:
            self.all_playlists = []
            return

        all_entries = [(i["id"], i["title"]) for i in playlists["entries"]]
        self.all_playlists = all_entries

    def _notify_single_playlist(self, idx, total, waiting=None):
        """send notification"""
        channel_name = self.json_data["channel_name"]
        message = [
            f"{channel_name}: Scanning channel for playlists",
            f"Progress: {idx + 1}/{total}",
        ]
        if waiting:
            message.append(waiting)

        self.task.send_progress(message, progress=(idx + 1) / total)

    def _index_single_playlist(self, playlist):
        """add single playlist if needed"""
        from playlist.src.index import YoutubePlaylist

        try:
            playlist = YoutubePlaylist(playlist[0])
            playlist.update_playlist(skip_on_empty=True)
        except ValueError as err:
            message = [
                f"{self.youtube_id}: skip failed playlist import",
                str(err),
            ]
            print(message)
            if self.task:
                self.task.send_progress(message)

    def get_channel_videos(self):
        """get all videos from channel"""
        data = {
            "query": {
                "term": {"channel.channel_id": {"value": self.youtube_id}}
            },
            "_source": ["youtube_id", "vid_type"],
        }
        all_videos = IndexPaginate("ta_video", data).get_results()
        return all_videos

    def get_overwrites(self) -> dict:
        """get all per channel overwrites"""
        return self.json_data.get("channel_overwrites", {})

    def set_overwrites(self, overwrites):
        """set per channel overwrites"""
        valid_keys = [
            "download_format",
            "autodelete_days",
            "index_playlists",
            "integrate_sponsorblock",
            "subscriptions_channel_size",
            "subscriptions_live_channel_size",
            "subscriptions_shorts_channel_size",
        ]

        to_write = self.json_data.get("channel_overwrites", {})
        for key, value in overwrites.items():
            if key not in valid_keys:
                raise ValueError(f"invalid overwrite key: {key}")

            if value is None and key in to_write:
                to_write.pop(key)
                continue

            to_write.update({key: value})

        self.json_data["channel_overwrites"] = to_write


class ChannelDelete(YouTubeItem):
    """delete and cleanup"""

    index_name = "ta_channel"

    def __init__(self, json_data):
        super().__init__(youtube_id=json_data["channel_id"])
        self.json_data = json_data

    def delete(self):
        """delete channel and all videos"""
        folder_path = self._get_folder_path()
        print(f"{self.youtube_id}: delete all media files")
        try:
            all_videos = os.listdir(folder_path)
            for video in all_videos:
                video_path = os.path.join(folder_path, video)
                os.remove(video_path)
            os.rmdir(folder_path)
        except FileNotFoundError:
            print(f"no videos found for {folder_path}")

        print(f"{self.youtube_id}: delete indexed playlists")
        self._delete_playlists()
        print(f"{self.youtube_id}: delete indexed videos")
        self._delete_es_videos()
        self._delete_es_comments()
        self._delete_es_subtitles()
        self.del_in_es()

    def _get_folder_path(self):
        """get folder where media files get stored"""
        folder_path = os.path.join(
            EnvironmentSettings.MEDIA_DIR,
            self.json_data["channel_id"],
        )
        return folder_path

    def _delete_es_videos(self):
        """delete all channel documents from elasticsearch"""
        data = {
            "query": {
                "term": {"channel.channel_id": {"value": self.youtube_id}}
            }
        }
        _, _ = ElasticWrap("ta_video/_delete_by_query").post(data)

    def _delete_es_comments(self):
        """delete all comments from this channel"""
        data = {
            "query": {
                "term": {"comment_channel_id": {"value": self.youtube_id}}
            }
        }
        _, _ = ElasticWrap("ta_comment/_delete_by_query").post(data)

    def _delete_es_subtitles(self):
        """delete all subtitles from this channel"""
        data = {
            "query": {
                "term": {"subtitle_channel_id": {"value": self.youtube_id}}
            }
        }
        _, _ = ElasticWrap("ta_subtitle/_delete_by_query").post(data)

    def _delete_playlists(self):
        """delete all indexed playlist from es"""
        from playlist.src.index import YoutubePlaylist

        all_playlists = self._get_indexed_playlists()
        for playlist in all_playlists:
            YoutubePlaylist(playlist["playlist_id"]).delete_metadata()

    def _get_indexed_playlists(self, active_only=False):
        """get all indexed playlists from channel"""
        must_list = [
            {"term": {"playlist_channel_id": {"value": self.youtube_id}}}
        ]
        if active_only:
            must_list.append({"term": {"playlist_active": {"value": True}}})

        data = {"query": {"bool": {"must": must_list}}}

        all_playlists = IndexPaginate("ta_playlist", data).get_results()
        return all_playlists


class ChannelVideoTypeDelete:
    """delete every video of one type from a channel

    Video by video, not a delete_by_query. ChannelDelete can be that
    blunt because it removes the whole channel folder afterwards, which
    takes the subtitle files with it. Here the folder stays and the
    other types stay in it, so every video has to go through
    YoutubeVideo.delete_media_file() - the only path that clears
    subtitle files off disk as well as comments, playlist entries and
    the index.
    """

    def __init__(
        self,
        channel_id: str,
        vid_type: str,
        task=None,
        ignore: bool = False,
    ):
        self.channel_id = channel_id
        self.vid_type = vid_type
        self.task = task
        self.ignore = ignore

    def delete(self) -> int:
        """delete all videos of the type, return how many went"""
        # local import, video.src.index imports this module
        from video.src.index import YoutubeVideo

        youtube_ids = self.get_video_ids()
        total = len(youtube_ids)
        print(f"{self.channel_id}: delete {total} {self.vid_type}")

        deleted = 0
        to_ignore: list[dict] = []
        for idx, youtube_id in enumerate(youtube_ids, start=1):
            if self.task:
                if self.task.is_stopped():
                    print(f"{self.channel_id}: delete stopped by user")
                    break

                self._notify(idx, total)

            video = YoutubeVideo(youtube_id)
            if self.ignore:
                # read it before the delete takes the document away
                video.get_from_es()
                if video.json_data:
                    to_ignore.append(self._build_ignore_doc(video.json_data))

            try:
                video.delete_media_file()
                deleted += 1
            except FileNotFoundError:
                # already gone from the index between the query and here
                print(f"{youtube_id}: not indexed, skipping")

        # after the loop, so a stopped run still ignores what it deleted
        self._write_ignore(to_ignore)

        return deleted

    @staticmethod
    def _build_ignore_doc(json_data: dict) -> dict:
        """build a ta_download ignore entry from the indexed video

        Everything the download queue needs is already on the video
        document, so this costs no youtube requests - unlike the single
        video "Delete and Ignore" button, which routes through
        extract_download and re-extracts the metadata it already has.
        """
        channel = json_data.get("channel") or {}
        player = json_data.get("player") or {}

        return {
            "channel_id": channel.get("channel_id"),
            "channel_indexed": True,
            "channel_name": channel.get("channel_name"),
            "duration": player.get("duration_str") or "NA",
            "published": json_data.get("published"),
            "timestamp": int(datetime.now().timestamp()),
            "title": json_data.get("title"),
            "vid_thumb_url": json_data.get("vid_thumb_url"),
            "vid_type": json_data.get("vid_type"),
            "youtube_id": json_data["youtube_id"],
            "status": "ignore",
            "auto_start": False,
        }

    def _write_ignore(self, docs: list[dict]) -> None:
        """bulk add the deleted videos to the ignore list"""
        if not docs:
            return

        bulk_list = []
        for doc in docs:
            action = {
                "index": {"_index": "ta_download", "_id": doc["youtube_id"]}
            }
            bulk_list.append(json.dumps(action))
            bulk_list.append(json.dumps(doc))

        bulk_list.append("\n")
        query_str = "\n".join(bulk_list)
        _, status_code = ElasticWrap("_bulk").post(query_str, ndjson=True)
        if status_code not in [200, 201]:
            print(f"{self.channel_id}: failed writing ignore entries")
            return

        print(f"{self.channel_id}: ignored {len(docs)} {self.vid_type}")

    def get_video_ids(self) -> list[str]:
        """every indexed video id of this type in the channel"""
        data = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "term": {
                                "channel.channel_id": {
                                    "value": self.channel_id
                                }
                            }
                        },
                        {"term": {"vid_type": {"value": self.vid_type}}},
                    ]
                }
            },
            "_source": ["youtube_id"],
        }
        all_videos = IndexPaginate("ta_video", data).get_results()

        return [i["youtube_id"] for i in all_videos]

    def _notify(self, idx: int, total: int) -> None:
        """send progress back to task"""
        message = [f"Deleting {self.vid_type} {idx}/{total}"]
        self.task.send_progress(message, progress=idx / total)


def channel_overwrites(channel_id, overwrites):
    """collection to overwrite settings per channel"""
    channel = YoutubeChannel(channel_id)
    channel.build_json()
    channel.set_overwrites(overwrites)
    channel.upload_to_es()
    channel.sync_to_videos()

    return channel.json_data
