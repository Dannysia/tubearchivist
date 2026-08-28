"""
functionality:
- handle yt_dlp
- build options and post processor
- download video files
- move to archive
"""

import os
import shutil
from datetime import datetime

from appsettings.src.config import AppConfig
from channel.src.index import YoutubeChannel
from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap, IndexPaginate
from common.src.helper import (
    countdown_sleep,
    get_channel_overwrites,
    get_playlists,
    ignore_filelist,
)
from common.src.ta_redis import RedisQueue
from common.src.urlparser import ParsedURLType
from download.src.queue import PendingList
from download.src.yt_dlp_base import YtWrap
from playlist.src.index import YoutubePlaylist
from video.src.comments import CommentList
from video.src.constants import VideoTypeEnum
from video.src.index import YoutubeVideo, index_new_video


class DownloaderBase:
    """base class for shared config"""

    CACHE_DIR = EnvironmentSettings.CACHE_DIR
    MEDIA_DIR = EnvironmentSettings.MEDIA_DIR
    CHANNEL_QUEUE = "download:channel"
    PLAYLIST_QUEUE = "download:playlist:full"
    PLAYLIST_QUICK = "download:playlist:quick"
    VIDEO_QUEUE = "download:video"

    def __init__(self, task=None):
        self.task = task
        self.config = AppConfig().config
        self.channel_overwrites = get_channel_overwrites()
        self.now = int(datetime.now().timestamp())


class VideoDownloader(DownloaderBase):
    """handle the video download functionality"""

    def __init__(self, task=False):
        super().__init__(task)
        self.obs = False
        self._build_obs()

    def run_queue(self, auto_only=False) -> tuple[int, int]:
        """setup download queue in redis loop until no more items"""
        downloaded = 0
        failed = 0
        while True:
            video_data = self._get_next(auto_only)
            if self.task.is_stopped() or not video_data:
                self._reset_auto()
                break

            # every attempt spends the request the wait exists to pace,
            # so failures count too. A run whose downloads are all
            # failing is a bot block, which is the run that most needs
            # to slow down rather than the one allowed to skip it
            if (downloaded or failed) and not countdown_sleep(
                self.config,
                self.task,
                lambda msg: self._notify(video_data, msg),
                label="download",
            ):
                self._reset_auto()
                break

            youtube_id = video_data["youtube_id"]
            channel_id = video_data["channel_id"]
            print(f"{youtube_id}: Downloading video")
            self._notify(video_data, "Validate download format")

            success = self._dl_single_vid(youtube_id, channel_id)
            if not success:
                failed += 1
                continue

            self._notify(video_data, "Add video metadata to index", progress=1)
            video_type = VideoTypeEnum(video_data["vid_type"])
            vid_dict = index_new_video(youtube_id, video_type=video_type)
            RedisQueue(self.CHANNEL_QUEUE).add(channel_id)
            RedisQueue(self.VIDEO_QUEUE).add(youtube_id)

            self._notify(video_data, "Move downloaded file to archive")
            self.move_to_archive(vid_dict)
            self._delete_from_pending(youtube_id)
            downloaded += 1

        # post processing
        DownloadPostProcess(self.task).run()

        return downloaded, failed

    def _notify(self, video_data, message, progress=False):
        """send progress notification to task"""
        if not self.task:
            return

        typ = VideoTypeEnum(video_data["vid_type"]).value.rstrip("s").title()
        title = video_data.get("title")
        self.task.send_progress(
            [f"Processing {typ}: {title}", message], progress=progress
        )

    def _get_next(self, auto_only):
        """get next item in queue"""
        must_list = [{"term": {"status": {"value": "pending"}}}]
        must_not_list = [{"exists": {"field": "message"}}]
        if auto_only:
            must_list.append({"term": {"auto_start": {"value": True}}})

        data = {
            "size": 1,
            "query": {"bool": {"must": must_list, "must_not": must_not_list}},
            "sort": [
                {"auto_start": {"order": "desc"}},
                {"timestamp": {"order": "asc"}},
            ],
        }
        path = "ta_download/_search"
        response, _ = ElasticWrap(path).get(data=data)
        if not response["hits"]["hits"]:
            return False

        return response["hits"]["hits"][0]["_source"]

    def _progress_hook(self, response):
        """process the progress_hooks from yt_dlp"""
        progress = False
        try:
            size = response.get("_total_bytes_str")
            if size.strip() == "N/A":
                size = response.get("_total_bytes_estimate_str", "N/A")

            percent = response["_percent_str"]
            progress = float(percent.strip("%")) / 100
            speed = response["_speed_str"]
            eta = response["_eta_str"]
            message = f"{percent} of {size} at {speed} - time left: {eta}"
        except KeyError:
            message = "processing"

        if self.task:
            title = response["info_dict"]["title"]
            self.task.send_progress([title, message], progress=progress)

    def _build_obs(self):
        """collection to build all obs passed to yt-dlp"""
        self._build_obs_basic()
        self._build_obs_user()
        self._build_obs_postprocessors()

    def _build_obs_basic(self):
        """initial obs"""
        self.obs = {
            "merge_output_format": "mp4",
            "outtmpl": (self.CACHE_DIR + "/download/%(id)s.mp4"),
            "progress_hooks": [self._progress_hook],
            "noprogress": True,
            "continuedl": True,
            "writethumbnail": False,
            "noplaylist": True,
            "color": "no_color",
        }

    def _build_obs_user(self):
        """build user customized options"""
        if self.config["downloads"]["format"]:
            self.obs["format"] = self.config["downloads"]["format"]
        if self.config["downloads"]["format_sort"]:
            format_sort = self.config["downloads"]["format_sort"]
            format_sort_list = [i.strip() for i in format_sort.split(",")]
            self.obs["format_sort"] = format_sort_list
        if self.config["downloads"]["limit_speed"]:
            self.obs["ratelimit"] = (
                self.config["downloads"]["limit_speed"] * 1024
            )

        throttle = self.config["downloads"]["throttledratelimit"]
        if throttle:
            self.obs["throttledratelimit"] = throttle * 1024

    def _build_obs_postprocessors(self):
        """add postprocessor to obs"""
        postprocessors = []

        if self.config["downloads"]["add_metadata"]:
            # full metadata is added in DownloadPostProcess
            postprocessors.append(
                {
                    "key": "FFmpegMetadata",
                    "add_chapters": True,
                }
            )

        self.obs["postprocessors"] = postprocessors

    def _set_overwrites(self, obs: dict, channel_id: str) -> None:
        """add overwrites to obs"""
        overwrites = self.channel_overwrites.get(channel_id)
        if overwrites and overwrites.get("download_format"):
            obs["format"] = overwrites.get("download_format")

    def _dl_single_vid(self, youtube_id: str, channel_id: str) -> bool:
        """download single video"""
        obs = self.obs.copy()
        self._set_overwrites(obs, channel_id)
        dl_cache = os.path.join(self.CACHE_DIR, "download")

        success, message = YtWrap(obs, self.config).download(youtube_id)
        if not success:
            self._handle_error(youtube_id, message)

        if self.obs["writethumbnail"]:
            # webp files don't get cleaned up automatically
            all_cached = ignore_filelist(os.listdir(dl_cache))
            to_clean = [i for i in all_cached if not i.endswith(".mp4")]
            for file_name in to_clean:
                file_path = os.path.join(dl_cache, file_name)
                os.remove(file_path)

        return success

    @staticmethod
    def _handle_error(youtube_id, message):
        """store error message"""
        data = {"doc": {"message": message}}
        _, _ = ElasticWrap(f"ta_download/_update/{youtube_id}").post(data=data)

    def move_to_archive(self, vid_dict):
        """move downloaded video from cache to archive"""
        host_uid = EnvironmentSettings.HOST_UID
        host_gid = EnvironmentSettings.HOST_GID
        # make folder
        folder = os.path.join(
            self.MEDIA_DIR, vid_dict["channel"]["channel_id"]
        )
        if not os.path.exists(folder):
            os.makedirs(folder)
            if host_uid and host_gid:
                os.chown(folder, host_uid, host_gid)
        # move media file
        media_file = vid_dict["youtube_id"] + ".mp4"
        old_path = os.path.join(self.CACHE_DIR, "download", media_file)
        new_path = os.path.join(self.MEDIA_DIR, vid_dict["media_url"])
        # move media file and fix permission
        shutil.move(old_path, new_path, copy_function=shutil.copyfile)
        if host_uid and host_gid:
            os.chown(new_path, host_uid, host_gid)

    @staticmethod
    def _delete_from_pending(youtube_id):
        """delete downloaded video from pending index if its there"""
        path = f"ta_download/_doc/{youtube_id}?refresh=true"
        _, _ = ElasticWrap(path).delete()

    def _reset_auto(self):
        """reset autostart to defaults after queue stop"""
        path = "ta_download/_update_by_query"
        data = {
            "query": {"term": {"auto_start": {"value": True}}},
            "script": {
                "source": "ctx._source.auto_start = false",
                "lang": "painless",
            },
        }
        response, _ = ElasticWrap(path).post(data=data)
        updated = response.get("updated")
        if updated:
            print(f"[download] reset auto start on {updated} videos.")


class DownloadPostProcess(DownloaderBase):
    """handle task to run after download queue finishes"""

    def run(self):
        """run all functions

        A stop skips the steps that would reach youtube. The local ones
        still run: they file work that is already downloaded rather than
        leaving it half done, and none of them cost a request. Without
        this the stop was swallowed here - refresh_playlist broke out of
        a wait that had been cut short and the comment index went
        straight to youtube with no pacing at all, which is the one
        thing the shortened wait is supposed to prevent.

        run_queue calls this even when a stop broke its own loop, so the
        first check is up front rather than only on refresh_playlist's
        return. Everything before that return reaches youtube too:
        auto delete re-extracts each video it ignores, and
        add_playlists_to_refresh asks youtube for the playlists of every
        channel with index_playlists set.

        Queueing the new videos for comments is not one of those steps -
        it is a redis write - so it happens either way. It has to: the
        clear below is the last thing holding those ids, and the comment
        queue is what carries them into the next run.
        """
        keep_going = not (self.task and self.task.is_stopped())
        if keep_going:
            self.auto_delete_all()
            self.auto_delete_overwrites()
            keep_going = self.refresh_playlist()
        else:
            # refresh_playlist owns this on the way past normally, where
            # it has to run before the full refresh queue is drained. A
            # stop skips that queue outright, so nothing was fully
            # refreshed and everything holding a new video wants the
            # quick match - without this the ids are cleared below and
            # those playlists never learn what was downloaded
            self._add_video_playlists()

        self.match_videos()

        comment_list = CommentList(task=self.task)
        comment_list.add(video_ids=RedisQueue(self.VIDEO_QUEUE).get_all())
        if keep_going:
            comment_list.index()

        self.embed_metadata()

        RedisQueue(self.VIDEO_QUEUE).clear()

    def auto_delete_all(self):
        """handle auto delete"""
        autodelete_days = self.config["downloads"]["autodelete_days"]
        if not autodelete_days:
            return

        print(f"auto delete older than {autodelete_days} days")
        now_lte = str(self.now - autodelete_days * 24 * 60 * 60)
        channel_overwrite = "channel.channel_overwrites.autodelete_days"
        data = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"player.watched_date": {"lte": now_lte}}},
                        {"term": {"player.watched": True}},
                    ],
                    "must_not": [
                        {"exists": {"field": channel_overwrite}},
                    ],
                }
            },
            "sort": [{"player.watched_date": {"order": "asc"}}],
        }
        self._auto_delete_watched(data)

    def auto_delete_overwrites(self):
        """handle per channel auto delete from overwrites"""
        for channel_id, value in self.channel_overwrites.items():
            if "autodelete_days" in value:
                autodelete_days = value.get("autodelete_days")
                if autodelete_days is None:
                    continue

                print(f"{channel_id}: delete older than {autodelete_days}d")
                now_lte = str(self.now - autodelete_days * 24 * 60 * 60)
                must_list = [
                    {"range": {"player.watched_date": {"lte": now_lte}}},
                    {"term": {"channel.channel_id": {"value": channel_id}}},
                    {"term": {"player.watched": True}},
                ]
                data = {
                    "query": {"bool": {"must": must_list}},
                    "sort": [{"player.watched_date": {"order": "desc"}}],
                }
                self._auto_delete_watched(data)

    @staticmethod
    def _auto_delete_watched(data) -> None:
        """delete watched videos after x days"""
        to_delete = IndexPaginate("ta_video", data).get_results()
        if not to_delete:
            return

        for video in to_delete:
            youtube_id = video["youtube_id"]
            print(f"{youtube_id}: auto delete video")
            YoutubeVideo(youtube_id).delete_media_file()

        print("add deleted to ignore list")

        parsed_ids: list[ParsedURLType] = []

        for video_item in to_delete:
            vid_type = getattr(VideoTypeEnum, video_item["vid_type"].upper())
            parsed_ids.append(
                {
                    "type": "video",
                    "url": video_item["youtube_id"],
                    "vid_type": vid_type,
                }
            )

        PendingList(youtube_ids=parsed_ids).parse_url_list(status="ignore")

    def refresh_playlist(self) -> bool:
        """match videos with playlists, False when a stop cut it short"""
        if not self.add_playlists_to_refresh():
            return False

        queue = RedisQueue(self.PLAYLIST_QUEUE)
        while True:
            total = queue.max_score()
            playlist_id, idx = queue.get_next()
            if not playlist_id or not idx or not total:
                break

            playlist = self._refresh_one_playlist(playlist_id)
            if not playlist:
                # update_playlist is what failed, so the request this
                # paces was already spent and the wait is still owed.
                # No notify: there is no title to count down against,
                # and the error above is worth leaving on screen
                if not countdown_sleep(self.config, self.task):
                    return False

                continue

            channel_name = playlist.json_data["playlist_channel"]
            playlist_title = playlist.json_data["playlist_name"]
            if self.task:
                self._notify_playlist(channel_name, playlist_title, idx, total)

            if not self._wait_for_next_playlist(
                queue, channel_name, playlist_title, idx, total
            ):
                return False

        return True

    def _refresh_one_playlist(self, playlist_id: str):
        """refresh a single playlist, None when its import failed"""
        try:
            playlist = YoutubePlaylist(playlist_id)
            playlist.update_playlist(skip_on_empty=True)
            if not playlist.json_data:
                raise ValueError("no json data extracted for playlist")

        except ValueError as err:
            message = [
                f"{playlist_id}: skip failed playlist import",
                str(err),
            ]
            print(message)
            if self.task:
                self.task.send_progress(message)

            return None

        return playlist

    def _notify_playlist(
        self, channel_name, playlist_title, idx, total, waiting=None
    ) -> None:
        """send progress for one refreshed playlist"""
        message = [
            f"Post Processing Playlists for: {channel_name}",
            f"{playlist_title} [{idx}/{total}]",
        ]
        if waiting:
            message.append(waiting)

        self.task.send_progress(message, progress=idx / total)

    def _wait_for_next_playlist(
        self, queue, channel_name, playlist_title, idx, total
    ) -> bool:
        """pace the next youtube request, naming it when there is one

        The wait used to sit behind an early continue for the no task
        case, so a scheduled refresh with nothing to report to paced
        itself not at all. countdown_sleep takes the no task case
        itself - it just sleeps.
        """
        if not self.task or not queue.length():
            return countdown_sleep(self.config, self.task)

        return countdown_sleep(
            self.config,
            self.task,
            lambda msg: self._notify_playlist(
                channel_name, playlist_title, idx, total, waiting=msg
            ),
            label="next playlist",
        )

    def add_playlists_to_refresh(self) -> bool:
        """collect the playlists to refresh, False when a stop cut it short

        _add_video_playlists has to run here rather than in run(),
        because its must_not reads the full refresh queue that the loop
        below has not drained yet - after the drain it would exclude
        nothing and re-queue everything just refreshed. That makes run()
        the second owner: a stop skips this method whole, so it calls
        _add_video_playlists itself on that path. Keep the two in step.
        """
        if self.task:
            message = ["Post Processing Playlists", "Scanning for Playlists"]
            self.task.send_progress(message)

        self._add_playlist_sub()
        keep_going = self._add_channel_playlists()
        self._add_video_playlists()

        return keep_going

    def _add_playlist_sub(self):
        """add subscribed playlists to refresh"""
        playlists = get_playlists(subscribed_only=True, source=["playlist_id"])
        to_add = [i["playlist_id"] for i in playlists]
        RedisQueue(self.PLAYLIST_QUEUE).add_list(to_add)

    def _add_channel_playlists(self) -> bool:
        """add playlists from channels, False when a stop cut it short

        get_all_playlists is a youtube request per channel that has
        index_playlists set, so this loop paces like every other one
        that reaches out. It used to do neither that nor a stop check,
        which made it the first thing a stopped download run went on to
        hammer youtube with.

        The stop check sits before get_next: a popped channel is off
        the queue for good, so leaving it unpopped is what gives its
        playlists another go on the next run.
        """
        queue = RedisQueue(self.CHANNEL_QUEUE)
        while True:
            if self.task and self.task.is_stopped():
                return False

            total = queue.max_score()
            channel_id, idx = queue.get_next()
            if not channel_id or not idx or not total:
                break

            channel = YoutubeChannel(channel_id)
            channel.get_from_es()
            if not channel.json_data:
                print(f"{channel_id}: skip failed channel import")
                continue

            overwrites = channel.get_overwrites()
            if not overwrites.get("index_playlists"):
                # nothing went to youtube, so there is nothing to pace
                continue

            self._notify_channel_scan(idx, total)
            channel.get_all_playlists()
            to_add = [i[0] for i in channel.all_playlists]
            RedisQueue(self.PLAYLIST_QUEUE).add_list(to_add)

            if not self._wait_for_next_channel(queue, idx, total):
                return False

        return True

    def _notify_channel_scan(self, idx, total, waiting=None) -> None:
        """send progress for one channel scanned for playlists"""
        if not self.task:
            return

        message = [
            "Post Processing Playlists",
            f"Scanning channel {idx}/{total} for playlists",
        ]
        if waiting:
            message.append(waiting)

        self.task.send_progress(message, progress=idx / total)

    def _wait_for_next_channel(self, queue, idx: int, total: int) -> bool:
        """pace the next youtube request, naming it when there is one"""
        if not self.task or not queue.length():
            return countdown_sleep(self.config, self.task)

        return countdown_sleep(
            self.config,
            self.task,
            lambda msg: self._notify_channel_scan(idx, total, waiting=msg),
            label="next channel",
        )

    def _add_video_playlists(self):
        """add other playlists for quick sync"""
        all_playlists = RedisQueue(self.PLAYLIST_QUEUE).get_all()
        must_not = [{"terms": {"playlist_id": all_playlists}}]
        video_ids = RedisQueue(self.VIDEO_QUEUE).get_all()
        must = [{"terms": {"playlist_entries.youtube_id": video_ids}}]
        data = {
            "query": {"bool": {"must_not": must_not, "must": must}},
            "_source": ["playlist_id"],
        }
        playlists = IndexPaginate("ta_playlist", data).get_results()
        to_add = [i["playlist_id"] for i in playlists]
        RedisQueue(self.PLAYLIST_QUICK).add_list(to_add)

    def match_videos(self) -> None:
        """scan rest of indexed playlists to match videos"""
        queue = RedisQueue(self.PLAYLIST_QUICK)
        while True:
            total = queue.max_score()
            playlist_id, idx = queue.get_next()
            if not playlist_id or not idx or not total:
                break

            playlist = YoutubePlaylist(playlist_id)
            playlist.get_from_es()
            if not playlist.json_data:
                print(f"{playlist_id}: skip failed playlist import")
                continue

            playlist.add_vids_to_playlist()
            playlist.remove_vids_from_playlist()
            playlist.match_local()

            if not self.task:
                continue

            message = [
                "Post Processing Playlists.",
                f"Validate Playlists: - {idx}/{total}",
            ]
            progress = idx / total
            self.task.send_progress(message, progress=progress)

    def embed_metadata(self):
        """embed metadata in media file"""
        if not self.config["downloads"].get("add_metadata"):
            return

        queue = RedisQueue(self.VIDEO_QUEUE)
        total = queue.max_score()
        video_ids = queue.get_all()

        for idx, youtube_id in enumerate(video_ids):
            YoutubeVideo(youtube_id).embed_metadata()

            if not self.task:
                continue

            message = [
                "Post Processing Videos.",
                f"Embed metadata: - {idx}/{total}",
            ]
            progress = idx / total
            self.task.send_progress(message, progress=progress)
