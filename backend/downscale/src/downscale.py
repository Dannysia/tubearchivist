import os
import select
import shlex
import shutil
import subprocess
import time
from datetime import datetime

from appsettings.src.config import AppConfig
from common.src.env_settings import EnvironmentSettings
from common.src.index_generic import IndexWriteError
from common.src.queue_interact import QueueWriteError
from common.src.ta_redis import RedisBase
from downscale.src.queue_interact import DownscaleInteract
from redis.exceptions import LockError
from task.src.task_manager import TaskCommand, TaskManager
from video.src.index import YoutubeVideo
from video.src.media_streams import MediaStreamExtractor

POLL_INTERVAL = 2
TERMINATE_TIMEOUT = 10
DISPATCH_LOCK_KEY = "downscale:dispatch-lock"
DISPATCH_LOCK_TIMEOUT = 30
DISPATCH_LOCK_BLOCKING_TIMEOUT = 10
# nothing frees a slot but an encode completing, which takes at least a
# minute in practice, so there is no point retrying on the 20s cadence
# transient lock contention uses
CONCURRENCY_RETRY_DELAY = 60


def _release_lock(lock) -> None:
    """
    redis-py raises LockError when the lock's TTL expired before we got
    here. The critical section is already done by then, so letting that
    out of a `finally` would replace the caller's return value with a
    failure that has nothing to do with the request.
    """
    try:
        lock.release()
    except LockError:
        print(f"downscale: lock {DISPATCH_LOCK_KEY} already expired")


# hardware (VAAPI) encoder keys all carry a _vaapi suffix; hw vs
# software is derived from the key rather than stored
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

# the libx264/libx265 named preset scale
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

# libsvtav1 takes a numeric 0 (slowest/best quality) - 13 (fastest)
# scale instead of named presets, approximated onto it here
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

# h264_vaapi's -quality (higher is faster) maps to Intel's "Target
# Usage", clamped by the driver to 1 (best quality, slowest) - 7
# (fastest, worst). hevc_vaapi and av1_vaapi expose no such option.
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

# h265_vaapi and av1_vaapi expose no preset option in ffmpeg, so
# whatever is configured is never really used for those two
PRESET_APPLIES = {"h264", "h265", "av1", "h264_vaapi"}


def is_hw_encoder(encoder_key: str) -> bool:
    return encoder_key.endswith("_vaapi")


def _preset_args(encoder_key: str, preset: str | None) -> list[str]:
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
    streams = MediaStreamExtractor(media_path).extract_metadata()
    heights = [s["height"] for s in streams if s["type"] == "video"]
    return max(heights) if heights else None


def _encode_args(
    encoder_key: str, quality: int, preset: str | None = None
) -> list[str]:
    encoder = ENCODER_SETTINGS.get(encoder_key, ENCODER_SETTINGS["h264"])
    args = [
        "-c:v",
        encoder["codec"],
        *_preset_args(encoder_key, preset),
        *encoder["extra_args"],
    ]

    if encoder_key == "av1_vaapi":
        # av1_vaapi has no -qp/CQP in ffmpeg the way h264_vaapi and
        # hevc_vaapi do - ICQ + -global_quality is its
        # constant-quality mode
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
    for a hardware encoder, decoding and scaling still happen in
    software - for compatibility with arbitrary source codecs - and only
    the encode runs on the GPU, fed via hwupload after the scale filter.
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


def dispatch_pending_downscales() -> None:
    """
    _reserve_slot() remains the source of truth for claiming a slot, via
    the same lock, so free_slots here is a hint: a task dispatched on it
    can still legitimately retry once if another dispatch won first.
    """
    lock = RedisBase().conn.lock(
        DISPATCH_LOCK_KEY, timeout=DISPATCH_LOCK_TIMEOUT
    )
    if not lock.acquire(
        blocking=True, blocking_timeout=DISPATCH_LOCK_BLOCKING_TIMEOUT
    ):
        # another dispatch is already covering whatever is free
        return

    try:
        max_concurrent = AppConfig().config["application"][
            "downscale_max_concurrent"
        ]
        if max_concurrent is None:
            free_slots = None
        elif max_concurrent == 0:
            # 0 disables local encoding outright, distinct from None,
            # which means unlimited
            return
        else:
            free_slots = max_concurrent - DownscaleInteract.count_running()
            if free_slots <= 0:
                return

        for job in DownscaleInteract.get_next_queued(free_slots):
            message = TaskCommand().start(
                "downscale_video",
                {
                    "youtube_id": job["youtube_id"],
                    "target_height": job["target_height"],
                    "doc_id": job["id"],
                },
            )
            try:
                DownscaleInteract(job["id"]).update(task_id=message["task_id"])
            except QueueWriteError as err:
                print(f"{job['id']}: task_id not recorded: {err}")
    finally:
        _release_lock(lock)


class DownscaleRunner:
    def __init__(self, task, youtube_id: str, target_height: int, doc_id: str):
        self.task = task
        self.youtube_id = youtube_id
        self.target_height = target_height
        self.doc_id: str = doc_id
        self.tmp_path: str | None = None
        # the settings _encode actually used, persisted on success
        self.encoder_key: str | None = None
        self.quality: int | None = None
        self.preset: str | None = None
        self.cmd: list[str] | None = None

    def run(self) -> None:
        """self.doc_id already exists, in status=queued"""
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
            self._mark_crashed(err)

    def _mark_crashed(self, err: Exception) -> None:
        self._cleanup_tmp()
        try:
            DownscaleInteract(self.doc_id).update(
                status="failed", message=str(err), updated=_now()
            )
        except QueueWriteError as write_err:
            print(f"{self.youtube_id}: not marked failed: {write_err}")

        dispatch_pending_downscales()

    def _reserve_slot(self, current_height: int, original_path: str) -> bool:
        """False means the caller should bail out without encoding"""
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
                max_concurrent is not None
                and DownscaleInteract.count_running() >= max_concurrent
            ):
                print(
                    f"{self.youtube_id}: max concurrent downscale jobs "
                    f"({max_concurrent}) reached, waiting for a free slot"
                )
                raise self.task.retry(countdown=CONCURRENCY_RETRY_DELAY)

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
            _release_lock(lock)

    def _encode(self, original_path: str, duration: float, title: str) -> None:
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

        self.cmd = _build_ffmpeg_cmd(
            original_path,
            self.target_height,
            encoder_key,
            quality,
            preset,
            self.tmp_path,
            vaapi_device,
        )
        process = subprocess.Popen(
            self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )  # pylint: disable=consider-using-with

        stderr_lines: list[str] = []

        while process.poll() is None:
            if self.task.is_stopped():
                self._terminate(process)
                self._cleanup_tmp()
                try:
                    DownscaleInteract(self.doc_id).delete_item()
                except QueueWriteError as err:
                    print(f"{self.youtube_id}: stop not recorded: {err}")

                dispatch_pending_downscales()
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
            dispatch_pending_downscales()

    def _drain_pipes(
        self,
        process: subprocess.Popen,
        duration: float,
        title: str,
        stderr_lines: list[str],
    ) -> None:
        """drain both pipes so neither fills up and blocks the encode"""
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
        new_height = _get_height(self.tmp_path)
        if not new_height:
            self._cleanup_tmp()
            DownscaleInteract(self.doc_id).update(
                status="failed",
                message="ffmpeg exited cleanly but output is invalid",
                updated=_now(),
            )
            dispatch_pending_downscales()
            return

        new_size = MediaStreamExtractor(self.tmp_path).get_file_size()
        DownscaleInteract(self.doc_id).update(
            status="pending_review",
            new_size=new_size,
            encoder=self.encoder_key,
            quality=self.quality,
            preset=self.preset,
            ffmpeg_args=shlex.join(self.cmd) if self.cmd else "",
            updated=_now(),
        )
        dispatch_pending_downscales()

    def _terminate(self, process: subprocess.Popen) -> None:
        process.terminate()
        try:
            process.wait(timeout=TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _cleanup_tmp(self) -> None:
        if self.tmp_path and os.path.exists(self.tmp_path):
            os.remove(self.tmp_path)


class DownscaleReview:
    def __init__(self, doc_id: str):
        self.doc_id = doc_id
        self.interact = DownscaleInteract(doc_id)

    def accept(self) -> str | None:
        """returns an error message on failure, None on success"""
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

        new_path = self._target_path(tmp_path, original_path)
        if new_path != original_path:
            media_url = video.json_data["media_url"]
            new_ext = os.path.splitext(new_path)[1]
            video.json_data["media_url"] = (
                os.path.splitext(media_url)[0] + new_ext
            )

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
            "ffmpeg_args": job.get("ffmpeg_args"),
        }

        video.add_streams(media_path=tmp_path)
        if not video.json_data.get("streams"):
            self.interact.update(
                status="failed",
                message="the encode could not be probed, original kept",
            )
            return "the encode could not be probed"

        self._replace_original(tmp_path, original_path, new_path)

        try:
            video.upload_to_es(checked=True)
        except IndexWriteError as err:
            self.interact.update(
                status="failed",
                message=f"file replaced, index not updated: {err}",
            )
            return "file replaced but the index was not updated"

        self.interact.delete_item()
        return None

    @staticmethod
    def _target_path(tmp_path: str, original_path: str) -> str:
        """
        matches tmp_path's container rather than assuming
        original_path's: a remote worker may encode to .mkv for HDR10
        static metadata that MP4 muxing does not reliably carry
        """
        tmp_ext = os.path.splitext(tmp_path)[1]
        original_ext = os.path.splitext(original_path)[1]
        if tmp_ext == original_ext:
            return original_path

        return os.path.splitext(original_path)[0] + tmp_ext

    def _replace_original(
        self, tmp_path: str, original_path: str, new_path: str
    ) -> None:
        self._move(tmp_path, new_path)
        if new_path != original_path and os.path.exists(original_path):
            os.remove(original_path)

    def reject(self) -> str | None:
        """the original file stays untouched"""
        job, status_code = self.interact.get_item()
        if status_code == 404 or not job:
            return "job not found"

        tmp_path = job.get("tmp_file_path")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        self.interact.delete_item()
        return None

    def retry(self) -> str | None:
        """target height and source file are re-validated at run time"""
        job, status_code = self.interact.get_item()
        if status_code == 404 or not job:
            return "job not found"

        if job["status"] != "failed":
            return f"job is not failed, status is {job['status']}"

        self.requeue(job)
        return None

    def requeue(self, job: dict) -> None:
        """
        does not dispatch: a caller requeueing many jobs should call
        dispatch_pending_downscales() once at the end, not once per job
        """
        tmp_path = job.get("tmp_file_path")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        self.interact.update(
            status="queued", message=None, task_id="", updated=_now()
        )

    def cancel(self) -> str | None:
        """
        a queued job has no process or tmp file yet, so its doc goes
        immediately rather than waiting up to a retry delay for the task
        to notice. A running job's ffmpeg can only be torn down from
        inside the task, so that one goes through poll-and-notice.
        """
        job, status_code = self.interact.get_item()
        if status_code == 404 or not job:
            return "job not found"

        if job["status"] not in ("queued", "running"):
            return f"job is not queued or running, status is {job['status']}"

        if job["status"] == "running" and job.get("worker"):
            # remote-held: no celery task to signal, only a worker
            # polling on its own schedule, so leave the doc in place -
            # the worker acks by deleting the job on its next
            # heartbeat. If it is already dead the lease reaper cleans
            # up once the lease goes stale.
            self.interact.update(stop_requested=True)
            return None

        task_id = job["task_id"]
        if not task_id:
            # queued but never dispatched, so no celery task exists to
            # signal - delete it directly
            self.interact.delete_item()
            return None

        if not TaskManager().get_task(task_id):
            # TaskRedis.set_command raises KeyError on an unknown
            # task_id instead of failing gracefully
            return "task not found, may not have started yet"

        TaskCommand().stop(task_id)

        if job["status"] == "queued":
            self.interact.delete_item()

        return None

    @staticmethod
    def _move(src: str, dst: str) -> None:
        """falls back to a copy across devices"""
        try:
            os.replace(src, dst)
        except OSError:
            shutil.move(src, dst)
