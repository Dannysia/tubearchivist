import os
import shutil

from appsettings.src.config import AppConfig
from common.src.env_settings import EnvironmentSettings
from common.src.queue_interact import QueueWriteError
from common.src.ta_redis import RedisBase
from downscale.src.downscale import (
    DISPATCH_LOCK_BLOCKING_TIMEOUT,
    DISPATCH_LOCK_KEY,
    DISPATCH_LOCK_TIMEOUT,
    _get_height,
    _now,
    _release_lock,
    dispatch_pending_downscales,
)
from downscale.src.queue_interact import DownscaleInteract
from video.src.index import YoutubeVideo
from video.src.media_streams import MediaStreamExtractor

STALE_LEASE_SECONDS = 60

NOT_HELD_ERROR = "job no longer held by this worker"
CANCELLED_ERROR = "job was cancelled"


def _own_job(doc_id: str, worker: str) -> tuple[dict | None, str | None]:
    """returns (job, None), or (None, error)"""
    job, status_code = DownscaleInteract(doc_id).get_item()
    if status_code == 404 or not job:
        return None, "job not found"

    if job.get("status") != "running" or job.get("worker") != worker:
        return None, NOT_HELD_ERROR

    return job, None


def _cleanup_tmp_files(tmp_path: str | None) -> None:
    if not tmp_path:
        return

    for path in (tmp_path, f"{tmp_path}.part"):
        if os.path.exists(path):
            os.remove(path)


def _discard(doc_id: str, tmp_path: str | None) -> None:
    _cleanup_tmp_files(tmp_path)
    try:
        DownscaleInteract(doc_id).delete_item()
    except QueueWriteError as err:
        print(f"{doc_id}: discard not recorded: {err}")

    dispatch_pending_downscales()


def claim(worker: str) -> dict | None:
    lock = RedisBase().conn.lock(
        DISPATCH_LOCK_KEY, timeout=DISPATCH_LOCK_TIMEOUT
    )
    if not lock.acquire(
        blocking=True, blocking_timeout=DISPATCH_LOCK_BLOCKING_TIMEOUT
    ):
        return None

    try:
        for job in DownscaleInteract.get_next_queued(None):
            try:
                claimed = _try_claim_candidate(job, worker)
            except QueueWriteError as err:
                print(f"{job['id']}: candidate skipped, {err}")
                continue

            if claimed:
                return claimed

        return None
    finally:
        _release_lock(lock)


def _try_claim_candidate(job: dict, worker: str) -> dict | None:
    """None means skip this candidate, not an error"""
    doc_id = job["id"]
    youtube_id = job["youtube_id"]

    video = YoutubeVideo(youtube_id)
    video.get_from_es()
    if not video.json_data:
        DownscaleInteract(doc_id).delete_item()
        return None

    original_path = os.path.join(
        EnvironmentSettings.MEDIA_DIR, video.json_data["media_url"]
    )
    if not os.path.exists(original_path):
        DownscaleInteract(doc_id).update(
            status="failed", message="source file missing", updated=_now()
        )
        return None

    target_height = job["target_height"]
    current_height = _get_height(original_path)
    if not current_height or target_height >= current_height:
        DownscaleInteract(doc_id).update(
            status="failed",
            message="target height no longer below current height",
            updated=_now(),
        )
        return None

    if DownscaleInteract.get_active_for_video(youtube_id, exclude_id=doc_id):
        DownscaleInteract(doc_id).delete_item()
        return None

    tmp_path = job["tmp_file_path"]
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)

    DownscaleInteract(doc_id).update(
        status="running",
        worker=worker,
        last_heartbeat=_now(),
        progress=0.0,
        current_height=current_height,
        original_size=MediaStreamExtractor(original_path).get_file_size(),
        tmp_file_path=tmp_path,
        updated=_now(),
    )

    quality_hint = AppConfig().config["application"]["downscale_crf"]
    if quality_hint is None:
        quality_hint = 23

    return {
        "id": doc_id,
        "youtube_id": youtube_id,
        "title": job["title"],
        "target_height": target_height,
        "quality_hint": quality_hint,
        # nginx's /youtube/ alias, not a django endpoint
        "source_url": f"/youtube/{video.json_data['media_url']}",
    }


def heartbeat(
    doc_id: str, worker: str, progress: float
) -> tuple[dict | None, str | None]:
    """returns {"stop": bool} from the doc's stop_requested"""
    job, error = _own_job(doc_id, worker)
    if error:
        return None, error

    DownscaleInteract(doc_id).update(last_heartbeat=_now(), progress=progress)
    return {"stop": bool(job.get("stop_requested"))}, None


def upload_result(doc_id: str, worker: str, stream) -> str | None:
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    tmp_path = job["tmp_file_path"]
    part_path = f"{tmp_path}.part"
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)

    with open(part_path, "wb") as dest:
        shutil.copyfileobj(stream, dest)

    job, error = _own_job(doc_id, worker)
    if error or job.get("stop_requested"):
        if os.path.exists(part_path):
            os.remove(part_path)
        return error or CANCELLED_ERROR

    os.replace(part_path, tmp_path)
    return None


def finish(
    doc_id: str,
    worker: str,
    encoder: str,
    quality: int,
    preset: str | None,
    ffmpeg_args: str,
) -> str | None:
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    tmp_path = job["tmp_file_path"]

    if job.get("stop_requested"):
        _discard(doc_id, tmp_path)
        return None

    new_height = _get_height(tmp_path)
    if not new_height:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        DownscaleInteract(doc_id).update(
            status="failed",
            message="ffmpeg finished but output is invalid",
            tmp_file_path=tmp_path,
            worker="",
            last_heartbeat=0,
            updated=_now(),
        )
        dispatch_pending_downscales()
        return None

    new_size = MediaStreamExtractor(tmp_path).get_file_size()
    DownscaleInteract(doc_id).update(
        status="pending_review",
        new_size=new_size,
        tmp_file_path=tmp_path,
        encoder=encoder,
        quality=quality,
        preset=preset,
        ffmpeg_args=ffmpeg_args,
        worker="",
        last_heartbeat=0,
        updated=_now(),
    )
    dispatch_pending_downscales()
    return None


def fail(doc_id: str, worker: str, message: str) -> str | None:
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    if job.get("stop_requested"):
        _discard(doc_id, job.get("tmp_file_path"))
        return None

    DownscaleInteract(doc_id).update(
        status="failed",
        message=message[-2000:],
        worker="",
        last_heartbeat=0,
        updated=_now(),
    )
    return None


def delete(doc_id: str, worker: str) -> str | None:
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    _discard(doc_id, job.get("tmp_file_path"))
    return None


def reap_stale_leases() -> None:
    stale_before = _now() - STALE_LEASE_SECONDS
    stale_jobs = DownscaleInteract.get_stale_leases(stale_before)
    if not stale_jobs:
        return

    for job in stale_jobs:
        doc_id = job["id"]
        tmp_path = job.get("tmp_file_path")

        try:
            if job.get("stop_requested"):
                _cleanup_tmp_files(tmp_path)
                DownscaleInteract(doc_id).delete_item()
                continue

            _cleanup_tmp_files(tmp_path)

            DownscaleInteract(doc_id).update(
                status="queued",
                message=None,
                task_id="",
                worker="",
                last_heartbeat=0,
                progress=0.0,
                stop_requested=False,
                updated=_now(),
            )
        except QueueWriteError as err:
            print(f"{doc_id}: lease not reaped, {err}")

    dispatch_pending_downscales()
