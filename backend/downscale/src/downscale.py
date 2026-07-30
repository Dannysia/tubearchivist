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
from task.src.task_manager import TaskCommand
from video.src.index import YoutubeVideo
from video.src.media_streams import MediaStreamExtractor

POLL_INTERVAL = 2
TERMINATE_TIMEOUT = 10
DISPATCH_LOCK_KEY = "downscale:dispatch-lock"
DISPATCH_LOCK_TIMEOUT = 30
DISPATCH_LOCK_BLOCKING_TIMEOUT = 10

# hardware (VAAPI) encoder keys all carry a _vaapi suffix; hw vs software
# is derived from the key rather than stored, so there's nothing to keep
# in sync when adding an encoder
ENCODER_SETTINGS = {
    "h264": {"codec": "libx264", "extra_args": []},
    "h264_vaapi": {"codec": "h264_vaapi", "extra_args": []},
    "h265": {
        "codec": "libx265",
        "extra_args": ["-tag:v", "hvc1"],
    },
    "h265_vaapi": {
        # ffmpeg's encoder is named hevc_vaapi, there is no h265_vaapi
        "codec": "hevc_vaapi",
        "extra_args": ["-tag:v", "hvc1"],
    },
    "av1": {"codec": "libsvtav1", "extra_args": []},
    "av1_vaapi": {"codec": "av1_vaapi", "extra_args": []},
}

# named speed presets exposed to the user, matching the libx264/libx265
# scale. VAAPI encoders have no equivalent knob in ffmpeg - speed/quality
# there is controlled by the driver, not a -preset flag - so PRESET_CHOICES
# only applies to software encoders.
PRESET_CHOICES = [
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
    "placebo",
]

# libsvtav1 uses a numeric 0 (slowest/best quality) - 13 (fastest) scale
# instead of named presets, so the chosen named preset is approximated onto
# it here. "veryfast" maps to 8 to match the previously hardcoded default.
AV1_PRESET_MAP = {
    "ultrafast": 12,
    "superfast": 10,
    "veryfast": 8,
    "faster": 7,
    "fast": 6,
    "medium": 5,
    "slow": 3,
    "slower": 2,
    "veryslow": 1,
    "placebo": 0,
}

# ffmpeg's h264_vaapi exposes a -quality option (higher is faster) that maps
# to Intel's "Target Usage" on VAAPI/Quick Sync hardware, typically clamped
# to a 1 (best quality, slowest) - 7 (fastest, worst quality) range by the
# driver. hevc_vaapi and av1_vaapi expose no such option in ffmpeg - there
# is nothing to map a preset onto for those two.
H264_VAAPI_QUALITY_MAP = {
    "ultrafast": 7,
    "superfast": 7,
    "veryfast": 6,
    "faster": 5,
    "fast": 5,
    "medium": 4,
    "slow": 3,
    "slower": 2,
    "veryslow": 1,
    "placebo": 1,
}

# encoders that actually apply the preset setting - h265_vaapi and
# av1_vaapi expose no such option, so a preset is never really "used" for
# either of those, regardless of what's configured
PRESET_APPLIES = {"h264", "h265", "av1", "h264_vaapi"}


def is_hw_encoder(encoder_key: str) -> bool:
    """hardware (VAAPI) encoder keys all carry a _vaapi suffix"""
    return encoder_key.endswith("_vaapi")


def _preset_args(encoder_key: str, preset: str | None) -> list[str]:
    """
    speed preset args for encoders that support one. h265_vaapi and
    av1_vaapi expose no such option in ffmpeg, so this is a no-op for
    those two.
    """
    if not preset:
        return []

    if encoder_key == "av1":
        numeric = AV1_PRESET_MAP.get(preset, AV1_PRESET_MAP["veryfast"])
        return ["-preset", str(numeric)]

    if encoder_key == "h264_vaapi":
        quality = H264_VAAPI_QUALITY_MAP.get(
            preset, H264_VAAPI_QUALITY_MAP["medium"]
        )
        return ["-quality", str(quality)]

    if encoder_key in ("h264", "h265"):
        return ["-preset", preset]

    return []


def missing_vaapi_device_message(vaapi_device: str) -> str | None:
    """None if the VAAPI render device exists, else an actionable message"""
    if os.path.exists(vaapi_device):
        return None

    return (
        f"VAAPI device {vaapi_device} not found - check /dev/dri "
        "passthrough in docker-compose"
    )


def _now() -> int:
    """current unix timestamp, seconds"""
    return int(datetime.now().timestamp())


def _get_height(media_path: str) -> int | None:
    """return the max video-stream height of a media file, if any"""
    streams = MediaStreamExtractor(media_path).extract_metadata()
    heights = [s["height"] for s in streams if s["type"] == "video"]
    return max(heights) if heights else None


def _encode_args(
    encoder_key: str, quality: int, preset: str | None = None
) -> list[str]:
    """
    build the -c:v/preset/quality portion of an ffmpeg command, shared
    between a real downscale encode and a synthetic capability test encode
    """
    encoder = ENCODER_SETTINGS.get(encoder_key, ENCODER_SETTINGS["h264"])
    args = [
        "-c:v",
        encoder["codec"],
        *_preset_args(encoder_key, preset),
        *encoder["extra_args"],
    ]

    if encoder_key == "av1_vaapi":
        # av1_vaapi doesn't expose -qp/CQP in ffmpeg like h264_vaapi and
        # hevc_vaapi do - ICQ + -global_quality is the mode it actually
        # supports for a constant-quality target
        args += ["-rc_mode", "ICQ", "-global_quality", str(quality)]
    elif is_hw_encoder(encoder_key):
        args += ["-rc_mode", "CQP", "-qp", str(quality)]
    else:
        args += ["-crf", str(quality)]

    return args


def _build_ffmpeg_cmd(
    original_path: str,
    target_height: int,
    encoder_key: str,
    quality: int,
    preset: str | None,
    tmp_path: str,
    vaapi_device: str,
) -> list[str]:
    """
    build the ffmpeg argv for a downscale encode. For a hardware encoder,
    decoding and scaling still happen in software (for compatibility with
    arbitrary source codecs) and only the encode step runs on the GPU, fed
    via hwupload after the scale filter.
    """
    is_hw = is_hw_encoder(encoder_key)

    cmd = ["ffmpeg", "-y"]
    if is_hw:
        cmd += ["-vaapi_device", vaapi_device]

    cmd += ["-i", original_path]

    video_filter = f"scale=-2:{target_height}"
    if is_hw:
        video_filter += ",format=nv12,hwupload"
    cmd += ["-vf", video_filter]

    cmd += _encode_args(encoder_key, quality, preset)

    cmd += [
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        "-loglevel",
        "warning",
        "-nostats",
        "-progress",
        "pipe:1",
        tmp_path,
    ]

    return cmd


class DownscaleRunner:
    """run a single downscale job for a video, called from the celery task"""

    def __init__(self, task, youtube_id: str, target_height: int, doc_id: str):
        self.task = task
        self.youtube_id = youtube_id
        self.target_height = target_height
        self.doc_id: str = doc_id
        self.tmp_path: str | None = None
        # populated by _encode with the settings actually used, so
        # _finish_success can persist what really produced this file
        self.encoder_key: str | None = None
        self.quality: int | None = None
        self.preset: str | None = None

    def run(self) -> None:
        """entry point. self.doc_id already exists in status=queued"""
        if self.task.is_stopped():
            DownscaleInteract(self.doc_id).delete_item()
            return

        video = YoutubeVideo(self.youtube_id)
        video.get_from_es()
        if not video.json_data:
            print(f"{self.youtube_id}: video not found, skip downscale")
            DownscaleInteract(self.doc_id).delete_item()
            return

        original_path = os.path.join(
            EnvironmentSettings.MEDIA_DIR, video.json_data["media_url"]
        )
        if not os.path.exists(original_path):
            print(f"{self.youtube_id}: source file missing, skip downscale")
            DownscaleInteract(self.doc_id).update(
                status="failed",
                message="source file missing",
                updated=_now(),
            )
            return

        current_height = _get_height(original_path)
        if not current_height or self.target_height >= current_height:
            print(
                f"{self.youtube_id}: target height {self.target_height} not "
                f"below current height {current_height}, skip downscale"
            )
            DownscaleInteract(self.doc_id).update(
                status="failed",
                message="target height no longer below current height",
                updated=_now(),
            )
            return

        if not self._reserve_slot(current_height, original_path):
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

    def _reserve_slot(self, current_height: int, original_path: str) -> bool:
        """
        atomically check for another active job on this video and the
        concurrency limit, then transition this job's queued doc to
        running. returns True if a slot was reserved, False if the
        caller should bail out without encoding
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
            if DownscaleInteract.get_active_for_video(
                self.youtube_id, exclude_id=self.doc_id
            ):
                print(
                    f"{self.youtube_id}: already has another active "
                    "downscale job, skip"
                )
                DownscaleInteract(self.doc_id).delete_item()
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

            DownscaleInteract(self.doc_id).update(
                status="running",
                current_height=current_height,
                original_size=MediaStreamExtractor(
                    original_path
                ).get_file_size(),
                tmp_file_path=self.tmp_path,
                task_id=self.task.request.id,
                updated=_now(),
            )
            return True
        finally:
            lock.release()

    def _encode(self, original_path: str, duration: float, title: str) -> None:
        """run ffmpeg, polling for progress and a stop signal"""
        config = AppConfig().config["application"]
        encoder_key = config["downscale_encoder"]

        vaapi_device = EnvironmentSettings.VAAPI_RENDER_DEVICE
        if is_hw_encoder(encoder_key):
            missing_message = missing_vaapi_device_message(vaapi_device)
            if missing_message:
                raise RuntimeError(missing_message)

        quality = config["downscale_crf"]
        if quality is None:
            quality = 23

        preset = config["downscale_preset"]
        if not preset:
            preset = "veryfast"

        self.encoder_key = encoder_key
        self.quality = quality
        self.preset = preset if encoder_key in PRESET_APPLIES else None

        cmd = _build_ffmpeg_cmd(
            original_path,
            self.target_height,
            encoder_key,
            quality,
            preset,
            self.tmp_path,
            vaapi_device,
        )
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
            status="pending_review",
            new_size=new_size,
            encoder=self.encoder_key,
            quality=self.quality,
            preset=self.preset,
            updated=_now(),
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
            "encoder": job.get("encoder"),
            "quality": job.get("quality"),
            "preset": job.get("preset"),
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

    def retry(self) -> str | None:
        """
        user-requested re-queue of a failed job. Target height and
        source file are re-validated by the worker when it actually
        runs, same as any other queued job.
        """
        job, status_code = self.interact.get_item()
        if status_code == 404 or not job:
            return "job not found"

        if job["status"] != "failed":
            return f"job is not failed, status is {job['status']}"

        self.requeue(job)
        return None

    def requeue(self, job: dict) -> None:
        """
        clean up any leftover tmp file and dispatch a fresh celery task
        for job, resetting its doc to status=queued. Shared by a
        user-initiated retry() and ta_startup's auto-resume of jobs
        interrupted by a restart. The doc flips to queued *before* the
        task is dispatched so a worker that picks it up immediately
        can't have its status write clobbered by this call.
        """
        tmp_path = job.get("tmp_file_path")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        self.interact.update(status="queued", message=None, updated=_now())
        message = TaskCommand().start(
            "downscale_video",
            {
                "youtube_id": job["youtube_id"],
                "target_height": job["target_height"],
                "doc_id": self.doc_id,
            },
        )
        self.interact.update(task_id=message["task_id"])

    @staticmethod
    def _move(src: str, dst: str) -> None:
        """move src to dst, falling back to copy across devices"""
        try:
            os.replace(src, dst)
        except OSError:
            shutil.move(src, dst)
