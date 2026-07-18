"""
functionality:
- run ffmpeg to downscale an already downloaded video to a lower resolution
- review (accept/reject) a finished downscale job
"""

import os
import select
import shutil
import subprocess
import time
from datetime import datetime

from appsettings.src.config import AppConfig
from common.src.env_settings import EnvironmentSettings
from common.src.ta_redis import RedisBase
from downscale.src.queue_interact import DownscaleInteract
from video.src.index import YoutubeVideo
from video.src.media_streams import MediaStreamExtractor

POLL_INTERVAL = 2
TERMINATE_TIMEOUT = 10
DISPATCH_LOCK_KEY = "downscale:dispatch-lock"
DISPATCH_LOCK_TIMEOUT = 30
DISPATCH_LOCK_BLOCKING_TIMEOUT = 10

ENCODER_SETTINGS = {
    "h264": {"codec": "libx264", "extra_args": ["-preset", "veryfast"]},
    "h265": {
        "codec": "libx265",
        "extra_args": ["-preset", "veryfast", "-tag:v", "hvc1"],
    },
    "av1": {"codec": "libsvtav1", "extra_args": ["-preset", "8"]},
}


def _now() -> int:
    """current unix timestamp, seconds"""
    return int(datetime.now().timestamp())


def _get_height(media_path: str) -> int | None:
    """return the max video-stream height of a media file, if any"""
    streams = MediaStreamExtractor(media_path).extract_metadata()
    heights = [s["height"] for s in streams if s["type"] == "video"]
    return max(heights) if heights else None


class DownscaleRunner:
    """run a single downscale job for a video, called from the celery task"""

    def __init__(self, task, youtube_id: str, target_height: int):
        self.task = task
        self.youtube_id = youtube_id
        self.target_height = target_height
        self.doc_id: str | None = None
        self.tmp_path: str | None = None

    def run(self) -> None:
        """entry point"""
        video = YoutubeVideo(self.youtube_id)
        video.get_from_es()
        if not video.json_data:
            print(f"{self.youtube_id}: video not found, skip downscale")
            return

        original_path = os.path.join(
            EnvironmentSettings.MEDIA_DIR, video.json_data["media_url"]
        )
        if not os.path.exists(original_path):
            print(f"{self.youtube_id}: source file missing, skip downscale")
            return

        current_height = _get_height(original_path)
        if not current_height or self.target_height >= current_height:
            print(
                f"{self.youtube_id}: target height {self.target_height} not "
                f"below current height {current_height}, skip downscale"
            )
            return

        if not self._reserve_slot(video, current_height, original_path):
            return

        duration = video.json_data.get("player", {}).get("duration") or 0

        try:
            self._encode(
                original_path,
                duration=duration,
                title=video.json_data["title"],
            )
        except Exception as err:  # pylint: disable=broad-except
            print(f"{self.youtube_id}: downscale crashed: {err}")
            self._cleanup_tmp()
            DownscaleInteract(self.doc_id).update(
                status="failed", message=str(err), updated=_now()
            )

    def _reserve_slot(
        self, video: YoutubeVideo, current_height: int, original_path: str
    ) -> bool:
        """
        atomically check for an existing job on this video and the
        concurrency limit, then create the running doc. returns True if
        a slot was reserved and the doc created, False if the caller
        should bail out without encoding
        """
        lock = RedisBase().conn.lock(
            DISPATCH_LOCK_KEY, timeout=DISPATCH_LOCK_TIMEOUT
        )
        acquired = lock.acquire(
            blocking=True, blocking_timeout=DISPATCH_LOCK_BLOCKING_TIMEOUT
        )
        if not acquired:
            print(
                f"{self.youtube_id}: could not acquire downscale dispatch "
                "lock, retrying"
            )
            raise self.task.retry()

        try:
            if DownscaleInteract.get_active_for_video(self.youtube_id):
                print(
                    f"{self.youtube_id}: already has an active downscale "
                    "job, skip"
                )
                return False

            max_concurrent = AppConfig().config["application"][
                "downscale_max_concurrent"
            ]
            if (
                max_concurrent
                and DownscaleInteract.count_running() >= max_concurrent
            ):
                print(
                    f"{self.youtube_id}: max concurrent downscale jobs "
                    f"({max_concurrent}) reached, waiting for a free slot"
                )
                raise self.task.retry()

            self.tmp_path = os.path.join(
                EnvironmentSettings.CACHE_DIR,
                "downscale",
                f"{self.youtube_id}_{self.target_height}p.mp4",
            )
            os.makedirs(os.path.dirname(self.tmp_path), exist_ok=True)

            self.doc_id = DownscaleInteract().create(
                {
                    "youtube_id": self.youtube_id,
                    "channel_id": video.json_data["channel"]["channel_id"],
                    "channel_name": video.json_data["channel"]["channel_name"],
                    "title": video.json_data["title"],
                    "vid_thumb_url": video.json_data.get("vid_thumb_url"),
                    "media_url": (
                        f"{EnvironmentSettings().get_media_root()}/"
                        f'{video.json_data["media_url"]}'
                    ),
                    "status": "running",
                    "current_height": current_height,
                    "target_height": self.target_height,
                    "original_size": MediaStreamExtractor(
                        original_path
                    ).get_file_size(),
                    "new_size": 0,
                    "tmp_file_path": self.tmp_path,
                    "task_id": self.task.request.id,
                    "timestamp": _now(),
                    "updated": _now(),
                }
            )
            return True
        finally:
            lock.release()

    def _encode(self, original_path: str, duration: float, title: str) -> None:
        """run ffmpeg, polling for progress and a stop signal"""
        config = AppConfig().config["application"]
        encoder = ENCODER_SETTINGS.get(
            config["downscale_encoder"], ENCODER_SETTINGS["h264"]
        )
        crf = config["downscale_crf"]
        if crf is None:
            crf = 23

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            original_path,
            "-vf",
            f"scale=-2:{self.target_height}",
            "-c:v",
            encoder["codec"],
            *encoder["extra_args"],
            "-crf",
            str(crf),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-loglevel",
            "warning",
            "-nostats",
            "-progress",
            "pipe:1",
            self.tmp_path,
        ]
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )  # pylint: disable=consider-using-with

        stderr_lines: list[str] = []

        while process.poll() is None:
            if self.task.is_stopped():
                self._terminate(process)
                self._cleanup_tmp()
                DownscaleInteract(self.doc_id).delete_item()
                return

            self._drain_pipes(process, duration, title, stderr_lines)
            time.sleep(POLL_INTERVAL)

        self._drain_pipes(process, duration, title, stderr_lines)
        stderr = "".join(stderr_lines)

        if process.returncode == 0:
            self._finish_success()
        else:
            self._cleanup_tmp()
            DownscaleInteract(self.doc_id).update(
                status="failed",
                message=stderr[-2000:],
                updated=_now(),
            )

    def _drain_pipes(
        self,
        process: subprocess.Popen,
        duration: float,
        title: str,
        stderr_lines: list[str],
    ) -> None:
        """
        drain ffmpeg's stdout/stderr so neither pipe fills up and blocks
        the encode, parsing -progress output from stdout and collecting
        stderr for the failure message
        """
        out_time_seconds = None
        readable = [
            stream
            for stream in (process.stdout, process.stderr)
            if stream is not None
        ]

        while readable:
            ready, _, _ = select.select(readable, [], [], 0)
            if not ready:
                break

            for stream in ready:
                line = stream.readline()
                if not line:
                    readable.remove(stream)
                    continue
                if stream is process.stdout and line.startswith(
                    "out_time_ms="
                ):
                    try:
                        out_time_seconds = (
                            int(line.split("=", 1)[1]) / 1_000_000
                        )
                    except ValueError:
                        pass
                elif stream is process.stderr:
                    stderr_lines.append(line)

        if duration and out_time_seconds is not None:
            fraction = min(out_time_seconds / duration, 1.0)
            self.task.send_progress(
                [f"Downscaling to {self.target_height}p"],
                progress=fraction,
                title=f"Downscaling: {title}",
            )

    def _finish_success(self) -> None:
        """sanity-check the ffmpeg output and mark it ready for review"""
        new_height = _get_height(self.tmp_path)
        if not new_height:
            self._cleanup_tmp()
            DownscaleInteract(self.doc_id).update(
                status="failed",
                message="ffmpeg exited cleanly but output is invalid",
                updated=_now(),
            )
            return

        new_size = MediaStreamExtractor(self.tmp_path).get_file_size()
        DownscaleInteract(self.doc_id).update(
            status="pending_review", new_size=new_size, updated=_now()
        )

    def _terminate(self, process: subprocess.Popen) -> None:
        """stop the running ffmpeg process"""
        process.terminate()
        try:
            process.wait(timeout=TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _cleanup_tmp(self) -> None:
        """remove a partial/leftover tmp output file"""
        if self.tmp_path and os.path.exists(self.tmp_path):
            os.remove(self.tmp_path)


class DownscaleReview:
    """accept or reject a finished downscale job"""

    def __init__(self, doc_id: str):
        self.doc_id = doc_id
        self.interact = DownscaleInteract(doc_id)

    def accept(self) -> str | None:
        """
        replace the original file with the downscaled candidate.
        returns an error message on failure, None on success
        """
        job, status_code = self.interact.get_item()
        if status_code == 404 or not job:
            return "job not found"

        if job["status"] != "pending_review":
            return f"job is not pending review, status is {job['status']}"

        tmp_path = job["tmp_file_path"]
        if not os.path.exists(tmp_path):
            self.interact.update(status="failed", message="tmp file missing")
            return "downscaled file missing"

        video = YoutubeVideo(job["youtube_id"])
        video.get_from_es()
        if not video.json_data:
            return "video no longer exists"

        original_path = os.path.join(
            EnvironmentSettings.MEDIA_DIR, video.json_data["media_url"]
        )
        if not os.path.exists(original_path):
            self.interact.update(
                status="failed", message="original file missing"
            )
            return "original file missing"

        self._move(tmp_path, original_path)

        existing = video.json_data.get("downscale") or {}
        video.json_data["downscale"] = {
            "original_height": existing.get(
                "original_height", job["current_height"]
            ),
            "original_size": existing.get(
                "original_size", job["original_size"]
            ),
            "new_height": job["target_height"],
            "new_size": job["new_size"],
        }

        video.add_streams(media_path=original_path)
        video.upload_to_es()

        self.interact.delete_item()
        return None

    def reject(self) -> str | None:
        """discard the downscaled candidate, original stays untouched"""
        job, status_code = self.interact.get_item()
        if status_code == 404 or not job:
            return "job not found"

        tmp_path = job.get("tmp_file_path")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        self.interact.delete_item()
        return None

    @staticmethod
    def _move(src: str, dst: str) -> None:
        """move src to dst, falling back to copy across devices"""
        try:
            os.replace(src, dst)
        except OSError:
            shutil.move(src, dst)
