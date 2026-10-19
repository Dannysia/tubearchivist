import json
import os
import select
import shlex
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime

from appsettings.src.config import AppConfig
from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import IndexWriteError
from common.src.queue_interact import QueueDocMissing
from common.src.ta_redis import RedisBase
from downscale.src.queue_interact import DownscaleInteract, max_video_height
from redis.exceptions import LockError
from task.src.task_manager import TaskCommand, TaskManager
from video.src.index import YoutubeVideo
from video.src.media_streams import MediaStreamExtractor

POLL_INTERVAL = 2
TERMINATE_TIMEOUT = 10
DISPATCH_LOCK_KEY = "downscale:dispatch-lock"
DISPATCH_LOCK_TIMEOUT = 30
DISPATCH_LOCK_BLOCKING_TIMEOUT = 10
CONCURRENCY_RETRY_DELAY = 60
ACCEPT_LOCK_TIMEOUT = 120
COPY_CHUNK_SIZE = 64 * 1024 * 1024


@contextmanager
def dispatch_lock():
    lock = RedisBase().conn.lock(
        DISPATCH_LOCK_KEY, timeout=DISPATCH_LOCK_TIMEOUT
    )
    acquired = lock.acquire(
        blocking=True, blocking_timeout=DISPATCH_LOCK_BLOCKING_TIMEOUT
    )
    try:
        yield acquired
    finally:
        if acquired:
            _release_lock(lock)


def _release_lock(lock) -> None:
    """redis-py raises LockError when the lock TTL already expired"""
    try:
        lock.release()
    except LockError:
        print(f"downscale: lock {lock.name} already expired")


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
    return int(datetime.now().timestamp())


def _get_height(media_path: str) -> int | None:
    return max_video_height(
        MediaStreamExtractor(media_path).extract_metadata()
    )


def _get_timing(media_path: str) -> tuple[str, str] | None:
    """(duration, video frame count) as ffprobe prints them"""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration:stream=nb_frames",
        "-of",
        "json",
        media_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        probed = json.loads(result.stdout)
        duration = probed["format"]["duration"]
        frames = probed["streams"][0]["nb_frames"]
    except (ValueError, KeyError, IndexError):
        return None

    return duration, frames


def _boxes_fill_file(media_path: str) -> bool:
    """an mp4's top level boxes tile the file exactly unless truncated"""
    file_size = os.path.getsize(media_path)
    position = 0
    with open(media_path, "rb") as media_file:
        while position < file_size:
            media_file.seek(position)
            header = media_file.read(16)
            if len(header) < 8:
                return False

            box_size = int.from_bytes(header[:4], "big")
            if box_size == 1:
                if len(header) < 16:
                    return False
                box_size = int.from_bytes(header[8:16], "big")
            elif box_size == 0:
                return True

            if box_size < 8:
                return False

            position += box_size

    return position == file_size


def verify_encode(
    tmp_path: str, original_path: str, expected_size: int
) -> str | None:
    """None if the encode is safe to replace the original with"""
    tmp_size = os.path.getsize(tmp_path)
    if tmp_size != expected_size:
        return (
            f"the encode changed since it finished, {tmp_size} bytes "
            f"instead of {expected_size}, original kept"
        )

    if not _boxes_fill_file(tmp_path):
        return "the encode is truncated, original kept"

    original_timing = _get_timing(original_path)
    tmp_timing = _get_timing(tmp_path)
    if original_timing is None or tmp_timing is None:
        return "could not read the frame count and duration, original kept"

    original_duration, original_frames = original_timing
    tmp_duration, tmp_frames = tmp_timing
    if tmp_frames != original_frames:
        return (
            f"the encode has {tmp_frames} frames but the original has "
            f"{original_frames}, original kept"
        )

    if tmp_duration != original_duration:
        return (
            f"the encode is {tmp_duration}s long but the original is "
            f"{original_duration}s, original kept"
        )

    return None


def check_source(
    doc_id: str, youtube_id: str, target_height: int
) -> dict | None:
    """None when the job was dropped or failed instead"""
    video = YoutubeVideo(youtube_id)
    video.get_from_es()
    if not video.json_data:
        print(f"{youtube_id}: video not found, skip downscale")
        DownscaleInteract(doc_id).delete_item()
        return None

    original_path = os.path.join(
        EnvironmentSettings.MEDIA_DIR, video.json_data["media_url"]
    )
    if not os.path.exists(original_path):
        print(f"{youtube_id}: source file missing, skip downscale")
        DownscaleInteract(doc_id).mark_failed("source file missing")
        return None

    current_height = _get_height(original_path)
    if not current_height or target_height >= current_height:
        print(
            f"{youtube_id}: target height {target_height} not below "
            f"current height {current_height}, skip downscale"
        )
        DownscaleInteract(doc_id).mark_failed(
            "target height no longer below current height"
        )
        return None

    return {
        "json_data": video.json_data,
        "original_path": original_path,
        "current_height": current_height,
    }


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


def finish_encode(doc_id: str, tmp_path: str, settings: dict, **fields):
    interact = DownscaleInteract(doc_id)
    if not _get_height(tmp_path):
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        interact.mark_failed("ffmpeg finished but output is invalid", **fields)
    else:
        interact.update(
            status="pending_review",
            new_size=MediaStreamExtractor(tmp_path).get_file_size(),
            updated=_now(),
            **settings,
            **fields,
        )

    dispatch_pending_downscales()


def dispatch_pending_downscales() -> None:
    with dispatch_lock() as acquired:
        if acquired:
            _dispatch_queued()


def _dispatch_queued() -> None:
    max_concurrent = AppConfig().config["application"][
        "downscale_max_concurrent"
    ]
    if max_concurrent is None:
        free_slots = None
    elif max_concurrent == 0:
        # 0 disables local encoding, None means unlimited
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
        except IndexWriteError as err:
            print(f"{job['id']}: task_id not recorded: {err}")


class DownscaleRunner:
    def __init__(self, task, youtube_id: str, target_height: int, doc_id: str):
        self.task = task
        self.youtube_id = youtube_id
        self.target_height = target_height
        self.doc_id: str = doc_id
        self.tmp_path: str | None = None
        self.encoder_key: str | None = None
        self.quality: int | None = None
        self.preset: str | None = None
        self.cmd: list[str] | None = None

    def run(self) -> None:
        try:
            video = self._prepare()
        except QueueDocMissing:
            print(f"{self.youtube_id}: job is gone, skip downscale")
            return
        except IndexWriteError as err:
            print(f"{self.youtube_id}: queue write failed, retrying: {err}")
            raise self.task.retry(countdown=CONCURRENCY_RETRY_DELAY) from err

        if not video:
            return

        try:
            self._encode(
                video["original_path"],
                duration=video["duration"],
                title=video["title"],
            )
        except Exception as err:  # pylint: disable=broad-except
            print(f"{self.youtube_id}: downscale crashed: {err}")
            self._mark_crashed(err)

    def _prepare(self) -> dict | None:
        if self.task.is_stopped():
            DownscaleInteract(self.doc_id).delete_item()
            return None

        source = check_source(self.doc_id, self.youtube_id, self.target_height)
        if not source or not self._reserve_slot(
            source["current_height"], source["original_path"]
        ):
            return None

        json_data = source["json_data"]
        return {
            "original_path": source["original_path"],
            "duration": json_data.get("player", {}).get("duration") or 0,
            "title": json_data["title"],
        }

    def _mark_crashed(self, err: Exception) -> None:
        self._cleanup_tmp()
        try:
            DownscaleInteract(self.doc_id).mark_failed(str(err))
        except IndexWriteError as write_err:
            print(f"{self.youtube_id}: not marked failed: {write_err}")

        dispatch_pending_downscales()

    def _still_ours(self) -> bool:
        job, _ = DownscaleInteract(self.doc_id).get_item()
        return bool(
            job
            and job.get("status") == "queued"
            and job.get("task_id") in ("", self.task.request.id)
        )

    def _reserve_slot(self, current_height: int, original_path: str) -> bool:
        with dispatch_lock() as acquired:
            if not acquired:
                print(
                    f"{self.youtube_id}: could not acquire downscale "
                    "dispatch lock, retrying"
                )
                raise self.task.retry()

            return self._reserve_locked(current_height, original_path)

    def _reserve_locked(self, current_height: int, original_path: str) -> bool:
        if not self._still_ours():
            print(f"{self.youtube_id}: job taken by another runner, skip")
            return False

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
        if max_concurrent == 0:
            print(f"{self.youtube_id}: local encoding is disabled, requeue")
            DownscaleInteract(self.doc_id).update(task_id="")
            return False

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
            original_size=MediaStreamExtractor(original_path).get_file_size(),
            tmp_file_path=self.tmp_path,
            task_id=self.task.request.id,
            updated=_now(),
        )
        return True

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
                except IndexWriteError as err:
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
            DownscaleInteract(self.doc_id).mark_failed(stderr)
            dispatch_pending_downscales()

    def _drain_pipes(
        self,
        process: subprocess.Popen,
        duration: float,
        title: str,
        stderr_lines: list[str],
    ) -> None:
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
        finish_encode(
            self.doc_id,
            self.tmp_path,
            {
                "encoder": self.encoder_key,
                "quality": self.quality,
                "preset": self.preset,
                "ffmpeg_args": shlex.join(self.cmd) if self.cmd else "",
            },
        )

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
        self._keep_alive = lambda: None

    def accept(self) -> str | None:
        """returns an error message on failure, None on success"""
        lock = RedisBase().conn.lock(
            f"downscale:accept:{self.doc_id}", timeout=ACCEPT_LOCK_TIMEOUT
        )
        if not lock.acquire(blocking=False):
            return "this job is already being accepted"

        self._keep_alive = lambda: lock.extend(
            ACCEPT_LOCK_TIMEOUT, replace_ttl=True
        )
        try:
            return self._accept()
        finally:
            _release_lock(lock)

    def _accept(self) -> str | None:
        job, _ = self.interact.get_item()
        if not job:
            return "job not found"

        if job["status"] != "pending_review":
            return f"job is not pending review, status is {job['status']}"

        tmp_path = job["tmp_file_path"]
        if not os.path.exists(tmp_path):
            self.interact.mark_failed("tmp file missing")
            return "downscaled file missing"

        video = YoutubeVideo(job["youtube_id"])
        video.get_from_es()
        if not video.json_data:
            return "video no longer exists"

        original_path = os.path.join(
            EnvironmentSettings.MEDIA_DIR, video.json_data["media_url"]
        )
        if not os.path.exists(original_path):
            self.interact.mark_failed("original file missing")
            return "original file missing"

        error = verify_encode(tmp_path, original_path, job["new_size"])
        if error:
            self.interact.mark_failed(error)
            return error

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
            self.interact.mark_failed(
                "the encode could not be probed, original kept"
            )
            return "the encode could not be probed"

        return self._swap_in(video, tmp_path, original_path)

    def _swap_in(self, video, tmp_path: str, original_path: str) -> str | None:
        try:
            backup_path = self._replace(tmp_path, original_path)
        except (OSError, LockError) as err:
            return f"could not replace the original, original kept: {err}"

        try:
            video.upload_to_es(checked=True)
        except IndexWriteError as err:
            return self._roll_back(backup_path, original_path, err)

        _remove_quietly(backup_path)
        self.interact.delete_item()
        _remove_quietly(tmp_path)
        return None

    def reject(self) -> str | None:
        job, _ = self.interact.get_item()
        if not job:
            return "job not found"

        tmp_path = job.get("tmp_file_path")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        self.interact.delete_item()
        return None

    def retry(self) -> str | None:
        job, _ = self.interact.get_item()
        if not job:
            return "job not found"

        if job["status"] != "failed":
            return f"job is not failed, status is {job['status']}"

        self.requeue(job)
        return None

    def requeue(self, job: dict) -> None:
        tmp_path = job.get("tmp_file_path")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        self.interact.update(
            status="queued",
            message=None,
            task_id="",
            new_size=0,
            progress=0.0,
            encoder=None,
            quality=None,
            preset=None,
            ffmpeg_args="",
            worker="",
            last_heartbeat=0,
            stop_requested=False,
            updated=_now(),
        )

    def cancel(self) -> str | None:
        job, _ = self.interact.get_item()
        if not job:
            return "job not found"

        if job["status"] not in ("queued", "running"):
            return f"job is not queued or running, status is {job['status']}"

        if job["status"] == "running" and job.get("worker"):
            self.interact.update(stop_requested=True)
            return None

        task_id = job["task_id"]
        started = bool(task_id) and bool(TaskManager().get_task(task_id))
        if started:
            TaskCommand().stop(task_id)

        if job["status"] == "queued" or not task_id:
            self.interact.delete_item()
            return None

        if not started:
            return "task not found, may not have started yet"

        return None

    def _replace(self, src: str, dst: str) -> str:
        """atomically swap src in for dst, returns dst's backup path"""
        dst_dir = os.path.dirname(dst)
        backup_path = os.path.join(dst_dir, f".{self.doc_id}.downscale-backup")
        staging_path = os.path.join(
            dst_dir, f".{self.doc_id}.downscale-staging"
        )
        _recover_backup(backup_path, dst)
        _make_backup(dst, backup_path, self._keep_alive)
        try:
            _copy_durably(src, staging_path, self._keep_alive)
            _copy_ownership(dst, staging_path)
            os.replace(staging_path, dst)
        except (OSError, LockError):
            _remove_quietly(staging_path)
            _remove_quietly(backup_path)
            raise

        return backup_path

    def _roll_back(
        self, backup_path: str, original_path: str, err: Exception
    ) -> str:
        try:
            os.replace(backup_path, original_path)
        except OSError as restore_err:
            self.interact.mark_failed(
                f"index not updated: {err}, and the original could not be "
                f"restored from {backup_path}: {restore_err}"
            )
            return (
                "the index was not updated and the original could not be "
                "restored"
            )

        return f"the index was not updated, original kept: {err}"


def _recover_backup(backup_path: str, original_path: str) -> None:
    """undo what an interrupted accept left behind"""
    if not os.path.exists(backup_path):
        return

    if os.path.samefile(backup_path, original_path):
        os.remove(backup_path)
    else:
        os.replace(backup_path, original_path)


def _make_backup(original_path: str, backup_path: str, keep_alive) -> None:
    try:
        os.link(original_path, backup_path)
    except OSError:
        partial_path = f"{backup_path}.partial"
        _copy_durably(original_path, partial_path, keep_alive)
        os.replace(partial_path, backup_path)


def _copy_durably(src: str, dst: str, keep_alive) -> None:
    try:
        with open(src, "rb") as src_file, open(dst, "wb") as dst_file:
            while chunk := src_file.read(COPY_CHUNK_SIZE):
                dst_file.write(chunk)
                keep_alive()
            dst_file.flush()
            os.fsync(dst_file.fileno())
    except (OSError, LockError):
        _remove_quietly(dst)
        raise


def _copy_ownership(reference: str, path: str) -> None:
    shutil.copymode(reference, path)
    stat_result = os.stat(reference)
    try:
        os.chown(path, stat_result.st_uid, stat_result.st_gid)
    except PermissionError:
        pass


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError as err:
        if os.path.exists(path):
            print(f"downscale: could not remove {path}: {err}")
