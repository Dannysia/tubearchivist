"""
Functionality:
- Handle manual import task
- Scan and identify media files in import folder
- Process import media files
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime

from appsettings.src.config import AppConfig
from common.src.env_settings import EnvironmentSettings
from common.src.helper import (
    MEDIA_INDEX_ERRORS,
    NETWORK_ERRORS,
    countdown_sleep,
    ignore_filelist,
    is_missing,
)
from common.src.queue_interact import QueueWriteError
from download.src.queue_interact import PendingInteract
from download.src.thumbnails import ThumbManager
from PIL import Image
from video.src.comments import Comments
from video.src.index import YoutubeVideo
from video.src.meta_embed import IndexFromEmbed
from yt_dlp.utils import ISO639Utils


def extract_video_id(base_name: str) -> str | None:
    # yt-dlp default like [youtubeid]
    id_search = re.search(r"\[([a-zA-Z0-9_-]{11})\]$", base_name)
    if id_search:
        return id_search.group(1)

    file_name_search = re.search(r"([a-zA-Z0-9_-]{11})$", base_name)
    if file_name_search:
        return file_name_search.group(1)

    return None


# no dot allowed, channel_id becomes a directory name
CHANNEL_ID_PATTERN = r"[a-zA-Z0-9_-]{2,64}"
VIDEO_ID_PATTERN = r"[a-zA-Z0-9_-]{11}"

# sentinel for a count the info.json does not carry
UNKNOWN_COUNT = -1


def is_safe_channel_id(channel_id: str | None) -> bool:
    return bool(re.fullmatch(CHANNEL_ID_PATTERN, channel_id or ""))


def is_video_id(video_id: str | None) -> bool:
    return bool(re.fullmatch(VIDEO_ID_PATTERN, video_id or ""))


def strict_video_id(base_name: str) -> str | None:
    id_search = re.search(r"\[([a-zA-Z0-9_-]{11})\]$", base_name)
    if id_search:
        return id_search.group(1)

    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", base_name):
        return base_name

    return None


class ImportFolderScanner:
    """import and indexing existing video files
    - identify all media files belonging to a video
    - identify youtube id
    - convert if needed
    """

    CACHE_DIR = EnvironmentSettings.CACHE_DIR
    IMPORT_DIR = os.path.join(CACHE_DIR, "import")

    """All extensions should be in lowercase until better handling is in place.
    Described in Issue #502.
    """
    EXT_MAP = {
        "media": [".mp4", ".mkv", ".webm"],
        "metadata": [".json"],
        "thumb": [".jpg", ".png", ".webp"],
        "subtitle": [".vtt"],
    }

    def __init__(
        self,
        task=False,
        ignore_error: bool = False,
        prefer_local: bool = False,
    ):
        self.task = task
        self.to_import = False
        self.ignore_error = ignore_error
        self.prefer_local = prefer_local
        self.failed: list[str] = []

    def scan(self):
        """scan and match media files"""
        if self.task:
            self.task.send_progress(["Scanning your import folder."])

        all_files = self.get_all_files()
        self.match_files(all_files)
        self.process_videos()
        if self.failed:
            raise ValueError("; ".join(self.failed))

        return self.to_import

    def get_all_files(self):
        """get all files in /import"""
        rel_paths = ignore_filelist(os.listdir(self.IMPORT_DIR))
        all_files = [os.path.join(self.IMPORT_DIR, i) for i in rel_paths]
        all_files.sort()

        return all_files

    @staticmethod
    def _get_template():
        """base dict for video"""
        return {
            "media": False,
            "video_id": False,
            "metadata": False,
            "thumb": False,
            "subtitle": [],
        }

    def match_files(self, all_files):
        """loop through all files, join what matches"""
        self.to_import = []

        current_video = self._get_template()
        last_base = False

        for file_path in all_files:
            base_name, ext = self._detect_base_name(file_path)
            key, file_path = self._detect_type(file_path, ext)
            if not key or not file_path:
                continue

            if base_name != last_base:
                if last_base:
                    print(f"manual import: {current_video}")
                    self.to_import.append(current_video)

                current_video = self._get_template()
                last_base = base_name

            if key == "subtitle":
                current_video["subtitle"].append(file_path)
            else:
                current_video[key] = file_path

        if current_video.get("media"):
            print(f"manual import: {current_video}")
            self.to_import.append(current_video)

    @staticmethod
    def _detect_base_name(file_path):
        """extract base_name and ext for matching"""
        base_name_raw, ext = os.path.splitext(file_path)
        base_name, ext2 = os.path.splitext(base_name_raw)

        if ext2:
            if ISO639Utils.short2long(ext2.strip(".")) or ext2 == ".info":
                # valid secondary extension
                return base_name, ext

        return base_name_raw, ext

    def _detect_type(self, file_path, ext):
        """detect metadata type for file"""

        for key, value in self.EXT_MAP.items():
            if ext.lower() in value:
                return key, file_path

        return False, False

    def process_videos(self):
        config = AppConfig().config
        self.failed = []
        for idx, current_video in enumerate(self.to_import):
            if not current_video["media"]:
                message = (
                    f"{current_video}: no matching media file found. "
                    "match_files pairs a video's files by base name, so "
                    "a sidecar has to be named for the media file it "
                    "belongs to, not just for the same video id"
                )
                print(message)
                self.failed.append(message)
                continue

            if self.task and self.task.is_stopped():
                print("manual import: stopped by user")
                break

            if idx:
                if not countdown_sleep(
                    config,
                    self.task,
                    lambda msg: self._notify(idx, current_video, waiting=msg),
                    label="import",
                ):
                    print("manual import: stopped by user")
                    break

            if self.task:
                self._notify(idx, current_video)

            try:
                self._process_video(current_video, config)
            except NETWORK_ERRORS:
                raise
            except MEDIA_INDEX_ERRORS as err:
                file_name = os.path.basename(current_video["media"])
                message = (
                    str(err)
                    if str(err).startswith(file_name)
                    else f"{file_name}: {err}"
                )
                print(f"manual import failed: {message}")
                self.failed.append(message)

    def _process_video(self, current_video, config):
        self._detect_youtube_id(current_video)
        self._dump_thumb(current_video)
        self._convert_thumb(current_video)
        self._get_subtitles(current_video)
        self._convert_video(current_video)

        print(f"manual import: {current_video}")
        ManualImport(
            current_video,
            config,
            ignore_error=self.ignore_error,
            prefer_local=self.prefer_local,
        ).run()

    def _notify(self, idx, current_video, waiting: str | None = None):
        """send notification back to task"""
        filename = os.path.split(current_video["media"])[-1]
        if len(filename) > 50:
            filename = filename[:50] + "..."

        total = len(self.to_import)
        message = [
            f"Import queue processing video {idx + 1}/{total}",
            filename,
        ]
        if waiting:
            message.append(waiting)

        progress = (idx + 1) / total
        self.task.send_progress(message, progress=progress)

    def _detect_youtube_id(self, current_video):
        """find video id from filename or json"""
        youtube_id = self._extract_id_from_filename(current_video["media"])
        if youtube_id:
            current_video["video_id"] = youtube_id
            return

        youtube_id = self._extract_id_from_json(current_video["metadata"])
        if youtube_id:
            current_video["video_id"] = youtube_id
            return

        file_name = os.path.basename(current_video["media"])
        raise ValueError(
            f"{file_name}: failed to find a video id, in the file name or "
            "in an info.json beside it"
        )

    @staticmethod
    def _extract_id_from_filename(file_name):
        """
        look at the file name for the youtube id
        expects filename ending in [<youtube_id>].<ext>
        """
        base_name, _ = os.path.splitext(file_name)
        youtube_id = extract_video_id(base_name)
        if youtube_id:
            return youtube_id

        print(f"id extraction failed from filename: {file_name}")

        return False

    def _extract_id_from_json(self, json_file: str | bool) -> str | None:
        """open json file and extract id"""
        if not json_file or not isinstance(json_file, str):
            return None

        json_path = os.path.join(self.CACHE_DIR, "import", json_file)
        with open(json_path, "r", encoding="utf-8") as f:
            json_content = f.read()

        youtube_id = json.loads(json_content)["id"]

        return youtube_id

    def _dump_thumb(self, current_video):
        """extract embedded thumb before converting"""
        if current_video["thumb"]:
            return

        media_path = current_video["media"]
        _, ext = os.path.splitext(media_path)

        new_path = False
        ext = ext.lower()
        if ext == ".mkv":
            idx, thumb_type = self._get_mkv_thumb_stream(media_path)
            if idx is not None:
                new_path = self.dump_mpv_thumb(media_path, idx, thumb_type)

        elif ext == ".mp4":
            thumb_type = self.get_mp4_thumb_type(media_path)
            if thumb_type:
                new_path = self.dump_mp4_thumb(media_path, thumb_type)

        if new_path:
            current_video["thumb"] = new_path

    def _get_mkv_thumb_stream(self, media_path):
        """get stream idx of thumbnail for mkv files"""
        streams = self._get_streams(media_path)
        attachments = [
            i for i in streams["streams"] if i["codec_type"] == "attachment"
        ]

        for idx, stream in enumerate(attachments):
            tags = stream["tags"]
            if "mimetype" in tags and tags["filename"].startswith("cover"):
                _, ext = os.path.splitext(tags["filename"])
                return idx, ext

        return None, None

    @staticmethod
    def dump_mpv_thumb(media_path, idx, thumb_type):
        """write cover to disk for mkv"""
        _, media_ext = os.path.splitext(media_path)
        new_path = f"{media_path.rstrip(media_ext)}{thumb_type}"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "quiet",
                f"-dump_attachment:t:{idx}",
                new_path,
                "-i",
                media_path,
            ],
            check=False,
        )

        return new_path

    def get_mp4_thumb_type(self, media_path):
        """detect filetype of embedded thumbnail"""
        streams = self._get_streams(media_path)

        for stream in streams["streams"]:
            if stream["codec_name"] in ["png", "jpg"]:
                return stream["codec_name"]

        return False

    def _convert_thumb(self, current_video):
        """convert all thumbnails to jpg"""
        if not current_video["thumb"]:
            return

        thumb_path = current_video["thumb"]

        base_path, ext = os.path.splitext(thumb_path)
        if ext.lower() == ".jpg":
            return

        new_path = f"{base_path}.jpg"
        img_raw = Image.open(thumb_path)
        img_raw.convert("RGB").save(new_path)

        os.remove(thumb_path)
        current_video["thumb"] = new_path

    def _get_subtitles(self, current_video):
        """find all subtitles in media file"""
        if current_video["subtitle"]:
            return

        media_path = current_video["media"]
        streams = self._get_streams(media_path)
        base_path, ext = os.path.splitext(media_path)

        if ext.lower() == ".webm":
            print(f"{media_path}: subtitle extract from webm not supported")
            return

        for idx, stream in enumerate(streams["streams"]):
            if stream["codec_type"] == "subtitle":
                lang = ISO639Utils.long2short(stream["tags"]["language"])
                sub_path = f"{base_path}.{lang}.vtt"
                self._dump_subtitle(idx, media_path, sub_path)
                current_video["subtitle"].append(sub_path)

    @staticmethod
    def _dump_subtitle(idx, media_path, sub_path):
        """extract subtitle from media file"""
        subprocess.run(
            ["ffmpeg", "-i", media_path, "-map", f"0:{idx}", sub_path],
            check=True,
        )

    @staticmethod
    def _get_streams(media_path):
        """return all streams from media_path"""
        streams_raw = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-print_format",
                "json",
                media_path,
            ],
            capture_output=True,
            check=True,
        )
        streams = json.loads(streams_raw.stdout.decode())

        return streams

    @staticmethod
    def dump_mp4_thumb(media_path, thumb_type):
        """save cover to disk"""
        _, ext = os.path.splitext(media_path)
        new_path = f"{media_path.rstrip(ext)}.{thumb_type}"

        subprocess.run(
            [
                "ffmpeg",
                "-i",
                media_path,
                "-map",
                "0:v",
                "-map",
                "-0:V",
                "-c",
                "copy",
                new_path,
            ],
            check=True,
        )

        return new_path

    def _convert_video(self, current_video):
        """convert if needed"""
        current_path = current_video["media"]
        base_path, ext = os.path.splitext(current_path)
        if ext.lower() == ".mp4":
            return

        new_path = base_path + ".mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                current_path,
                new_path,
                "-loglevel",
                "warning",
                "-stats",
            ],
            check=True,
        )
        current_video["media"] = new_path
        os.remove(current_path)


class ManualImport:
    """import single identified video"""

    def __init__(
        self, current_video, config, ignore_error: bool, prefer_local: bool
    ):
        self.current_video = current_video
        self.config = config
        self.ignore_error: bool = ignore_error
        self.prefer_local: bool = prefer_local

    def run(self):
        """run all"""
        json_data = None
        if self.prefer_local:
            # embedded first
            json_data = IndexFromEmbed(
                self.current_video["media"],
                use_user_conf=False,
                config=self.config,
            ).run_index()
            if json_data:
                self._cleanup()
                return

        try:
            json_data = self.index_metadata()
        except ValueError as err:
            json_data = IndexFromEmbed(
                self.current_video["media"],
                use_user_conf=False,
                config=self.config,
            ).run_index()
            if not json_data:
                if not self.ignore_error:
                    raise

                print(f"manual import: skipping, {err}")

        if not json_data:
            return

        self._move_to_archive(json_data)
        self._cleanup()

        Comments(self.current_video["video_id"]).build_json(upload=True)
        YoutubeVideo(self.current_video["video_id"]).embed_metadata()

    def index_metadata(self) -> dict | None:
        """get metadata from yt or json"""
        video_id = self.current_video["video_id"]
        video = YoutubeVideo(video_id)
        info_json = self._get_info_json()
        try:
            video.build_json(
                youtube_meta_overwrite=info_json,
                media_path=self.current_video["media"],
                from_file=True,
            )
        except ValueError as err:
            message = self._why_no_metadata(video, info_json, err)
            raise ValueError(message) from err

        if not video.json_data:
            message = (
                f"{video_id}: manual import failed, and no metadata found."
            )
            print(message)
            if self.ignore_error:
                return None

            raise ValueError(message)

        video.check_subtitles(subtitle_files=self.current_video["subtitle"])
        video.upload_to_es()

        if video.offline_import and self.current_video["thumb"]:
            old_path = self.current_video["thumb"]
            thumbs = ThumbManager(video_id)
            new_path = thumbs.vid_thumb_path(absolute=True, create_folder=True)
            shutil.move(old_path, new_path, copy_function=shutil.copyfile)
        else:
            url = video.json_data["vid_thumb_url"]
            ThumbManager(video_id).download_video_thumb(url)

        return video.json_data

    def _why_no_metadata(self, video, info_json, err) -> str:
        file_name = os.path.basename(self.current_video["media"])
        if video.youtube_answered:
            return f"{file_name}: {err}"

        gone = (
            f"{file_name}: youtube returned no metadata for "
            f"{video.youtube_id} - either that id is not a video, or the "
            "video is no longer on youtube"
        )
        if info_json:
            return (
                f"{gone}, and the info.json beside the file did not fill "
                f"the gap: {err}"
            )

        return (
            f"{gone}. Check the id in the file name for a typo, or use "
            '"Generate metadata" in settings to write an info.json for it '
            "by hand"
        )

    def _get_info_json(self):
        """read info_json from file"""
        if not self.current_video["metadata"]:
            return False

        with open(self.current_video["metadata"], "r", encoding="utf-8") as f:
            info_json = json.loads(f.read())

        return info_json

    def _move_to_archive(self, json_data):
        """move identified media file to archive"""
        videos = EnvironmentSettings.MEDIA_DIR
        host_uid = EnvironmentSettings.HOST_UID
        host_gid = EnvironmentSettings.HOST_GID

        channel, file = os.path.split(json_data["media_url"])
        channel_folder = os.path.join(videos, channel)
        if not os.path.exists(channel_folder):
            os.makedirs(channel_folder)

        if host_uid and host_gid:
            os.chown(channel_folder, host_uid, host_gid)

        old_path = self.current_video["media"]
        new_path = os.path.join(channel_folder, file)
        shutil.move(old_path, new_path, copy_function=shutil.copyfile)
        if host_uid and host_gid:
            os.chown(new_path, host_uid, host_gid)

        base_name, _ = os.path.splitext(new_path)
        for old_path in self.current_video["subtitle"]:
            lang = old_path.split(".")[-2]
            new_path = f"{base_name}.{lang}.vtt"
            shutil.move(old_path, new_path, copy_function=shutil.copyfile)

    def _cleanup(self):
        """cleanup leftover files, clean up from queue"""
        meta_data = self.current_video["metadata"]
        if meta_data and os.path.exists(meta_data):
            os.remove(meta_data)

        thumb = self.current_video["thumb"]
        if thumb and os.path.exists(thumb):
            os.remove(thumb)

        for subtitle_file in self.current_video["subtitle"]:
            if os.path.exists(subtitle_file):
                os.remove(subtitle_file)

        video_id = self.current_video["video_id"]
        try:
            PendingInteract(youtube_id=video_id).delete_item(print_error=False)
        except QueueWriteError as err:
            print(f"{video_id}: queue entry not cleared: {err}")


class ImportFolderFiles:
    IMPORT_DIR = ImportFolderScanner.IMPORT_DIR
    PART_SUFFIX = ".part"
    PART_MAX_AGE = 24 * 60 * 60
    EXT_CATEGORY = {
        ext: key
        for key, value in ImportFolderScanner.EXT_MAP.items()
        for ext in value
    }

    @classmethod
    def _describe(cls, file_name: str) -> dict:
        file_path = os.path.join(cls.IMPORT_DIR, file_name)
        base_name, ext = ImportFolderScanner._detect_base_name(file_name)

        return {
            "filename": file_name,
            "size": os.path.getsize(file_path),
            "category": cls.EXT_CATEGORY.get(ext.lower()) or "unknown",
            "video_id": extract_video_id(base_name),
        }

    @classmethod
    def _clear_stale_parts(cls, all_files: list[str]) -> None:
        cutoff = datetime.now().timestamp() - cls.PART_MAX_AGE
        for file_name in all_files:
            if not file_name.endswith(cls.PART_SUFFIX):
                continue

            file_path = os.path.join(cls.IMPORT_DIR, file_name)
            if os.path.getmtime(file_path) < cutoff:
                print(f"import: clear stale part file {file_name}")
                os.remove(file_path)

    @classmethod
    def list_files(cls) -> list[dict]:
        os.makedirs(cls.IMPORT_DIR, exist_ok=True)
        all_files = ignore_filelist(os.listdir(cls.IMPORT_DIR))
        cls._clear_stale_parts(all_files)

        return [
            cls._describe(i)
            for i in sorted(all_files)
            if not i.endswith(cls.PART_SUFFIX)
            and os.path.isfile(os.path.join(cls.IMPORT_DIR, i))
        ]

    @classmethod
    def validate_name(cls, file_name: str | None) -> str:
        # the name is attacker controlled
        clean_name = os.path.basename(file_name or "").strip()
        if not clean_name or clean_name.startswith("."):
            raise ValueError(f"invalid file name: {file_name}")

        _, ext = os.path.splitext(clean_name)
        if ext.lower() not in cls.EXT_CATEGORY:
            raise ValueError(f"unsupported file type: {ext or clean_name}")

        base_name, _ = ImportFolderScanner._detect_base_name(clean_name)
        if not strict_video_id(base_name):
            raise ValueError(
                f"{clean_name}: name must be the 11 character video id, "
                "either on its own or in brackets like [video_id]"
            )

        return clean_name

    @classmethod
    def save(cls, upload) -> dict:
        clean_name = cls.validate_name(upload.name)
        os.makedirs(cls.IMPORT_DIR, exist_ok=True)
        file_path = os.path.join(cls.IMPORT_DIR, clean_name)
        part_path = f"{file_path}{cls.PART_SUFFIX}"

        try:
            with open(part_path, "wb") as f:
                for chunk in upload.chunks():
                    f.write(chunk)

            written = os.path.getsize(part_path)
            if upload.size is not None and written != upload.size:
                raise ValueError(
                    f"{clean_name}: incomplete upload, expected "
                    f"{upload.size} bytes but wrote {written}"
                )

            host_uid = EnvironmentSettings.HOST_UID
            host_gid = EnvironmentSettings.HOST_GID
            if host_uid and host_gid:
                os.chown(part_path, host_uid, host_gid)

            os.replace(part_path, file_path)
        except Exception:
            if os.path.exists(part_path):
                os.remove(part_path)

            raise

        return cls._describe(clean_name)

    @classmethod
    def metadata_name(cls, video_id: str) -> str:
        os.makedirs(cls.IMPORT_DIR, exist_ok=True)
        media_exts = ImportFolderScanner.EXT_MAP["media"]

        for file_name in sorted(ignore_filelist(os.listdir(cls.IMPORT_DIR))):
            base_name, ext = ImportFolderScanner._detect_base_name(file_name)
            if ext.lower() not in media_exts:
                continue

            if strict_video_id(base_name) == video_id:
                return f"{base_name}.info.json"

        return f"{video_id}.info.json"

    @classmethod
    def write_metadata(cls, validated: dict) -> dict:
        video_id = validated["video_id"]
        info_json = cls.build_info_json(validated)
        clean_name = cls.metadata_name(video_id)
        cls.validate_name(clean_name)

        os.makedirs(cls.IMPORT_DIR, exist_ok=True)
        file_path = os.path.join(cls.IMPORT_DIR, clean_name)
        part_path = f"{file_path}{cls.PART_SUFFIX}"

        try:
            with open(part_path, "w", encoding="utf-8") as f:
                json.dump(info_json, f, ensure_ascii=False, indent=2)

            host_uid = EnvironmentSettings.HOST_UID
            host_gid = EnvironmentSettings.HOST_GID
            if host_uid and host_gid:
                os.chown(part_path, host_uid, host_gid)

            os.replace(part_path, file_path)
        except Exception:
            if os.path.exists(part_path):
                os.remove(part_path)

            raise

        return cls._describe(clean_name)

    @staticmethod
    def build_info_json(validated: dict) -> dict:
        return {
            "id": validated["video_id"],
            "title": validated["title"],
            "channel_id": validated["channel_id"],
            "uploader": validated["channel_name"],
            # yt-dlp's YYYYMMDD
            "upload_date": validated["upload_date"].strftime("%Y%m%d"),
            "description": validated.get("description") or "",
            "thumbnail": validated.get("thumbnail") or "",
            # an explicit 0 is a real count
            "view_count": validated.get("view_count", UNKNOWN_COUNT),
            "like_count": validated.get("like_count", UNKNOWN_COUNT),
        }

    @classmethod
    def find_indexed(cls, file_names: list[str]) -> list[str]:
        by_id: dict[str, list[str]] = {}
        for file_name in file_names:
            base_name, _ = ImportFolderScanner._detect_base_name(file_name)
            video_id = strict_video_id(base_name)
            if video_id:
                by_id.setdefault(video_id, []).append(file_name)

        if not by_id:
            return []

        missing = set(is_missing(list(by_id), index_name="ta_video"))

        return sorted(
            file_name
            for video_id, names in by_id.items()
            if video_id not in missing
            for file_name in names
        )

    @classmethod
    def file_path(cls, file_name: str) -> str | None:
        clean_name = os.path.basename(file_name or "").strip()
        if not clean_name or clean_name.startswith("."):
            raise ValueError(f"invalid file name: {file_name}")

        file_path = os.path.join(cls.IMPORT_DIR, clean_name)
        if not os.path.isfile(file_path):
            return None

        return file_path

    @classmethod
    def delete_file(cls, file_name: str) -> bool:
        file_path = cls.file_path(file_name)
        if not file_path:
            return False

        os.remove(file_path)

        return True
