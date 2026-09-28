"""
a remote-held job is status="running" with worker set and task_id="" - it
has no celery task, so none of this goes through TaskCommand/TaskManager.
Job-scoped calls return an error string the caller turns into a 409.
"""

import os
import shutil

from appsettings.src.config import AppConfig
from common.src.env_settings import EnvironmentSettings
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

# three missed 10s heartbeats
STALE_LEASE_SECONDS = 60

NOT_HELD_ERROR = "job no longer held by this worker"
CANCELLED_ERROR = "job was cancelled"


def _own_job(doc_id: str, worker: str) -> tuple[dict | None, str | None]:
    """returns (job, None), or (None, error) when the caller must reject"""
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
    """dispatch after: clearing a job may free a concurrency slot"""
    _cleanup_tmp_files(tmp_path)
    DownscaleInteract(doc_id).delete_item()
    dispatch_pending_downscales()


def claim(worker: str) -> dict | None:
    """first claim wins: shares the dispatch lock with celery dispatch"""
    lock = RedisBase().conn.lock(
        DISPATCH_LOCK_KEY, timeout=DISPATCH_LOCK_TIMEOUT
    )
    if not lock.acquire(
        blocking=True, blocking_timeout=DISPATCH_LOCK_BLOCKING_TIMEOUT
    ):
        return None

    try:
        for job in DownscaleInteract.get_next_queued(None):
            claimed = _try_claim_candidate(job, worker)
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
        # nginx's /youtube/ alias, not a Django endpoint: FileResponse
        # over the ASGI worker pool retains the full file size in the
        # serving process for that process's lifetime, unreclaimable.
        # No ownership check - the same bytes are already reachable by
        # any authenticated user through the normal download path.
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
    """
    .part then rename, so a dropped connection never leaves a file that
    looks finished. tmp_file_path is deterministic across claims, so a
    reaped-and-reclaimed lease could land its rename on a new claim's
    output; the re-check before the rename narrows that window to a
    couple of ES round-trips rather than closing it.
    """
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


def _match_uploaded_container(tmp_path: str, container: str | None) -> str:
    """
    tmp_file_path is fixed at enqueue time with a hardcoded .mp4
    suffix, before it is known whether a local encode or a remote
    worker runs the job. A worker may produce a different container, so
    the doc would otherwise advertise a .mp4 path for other bytes all
    the way through review.
    """
    if not container:
        return tmp_path

    # the serializer allows only bare alphanumerics, so this swaps the
    # extension and cannot escape the cache dir
    new_path = f"{os.path.splitext(tmp_path)[0]}.{container.lower()}"
    if new_path == tmp_path or not os.path.exists(tmp_path):
        return tmp_path

    os.replace(tmp_path, new_path)
    return new_path


def finish(
    doc_id: str,
    worker: str,
    encoder: str,
    quality: int,
    preset: str | None,
    ffmpeg_args: str,
    container: str | None = None,
) -> str | None:
    """
    returns an error string only for the ownership case - an invalid
    upload is a normal failed job, not a rejected request
    """
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    tmp_path = job["tmp_file_path"]

    if job.get("stop_requested"):
        # cancel landed after the worker's last heartbeat: the encode
        # is valid but unwanted, so discard rather than offer it up
        _discard(doc_id, tmp_path)
        return None

    tmp_path = _match_uploaded_container(tmp_path, container)

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
        # already cancelled - don't leave a failed job for a retry the
        # user never asked for
        _discard(doc_id, job.get("tmp_file_path"))
        return None

    DownscaleInteract(doc_id).update(
        status="failed",
        # same cap as the local runner's ffmpeg stderr
        message=message[-2000:],
        worker="",
        last_heartbeat=0,
        updated=_now(),
    )
    return None


def delete(doc_id: str, worker: str) -> str | None:
    """the same end state the local cancel path reaches"""
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    _discard(doc_id, job.get("tmp_file_path"))
    return None


def reap_stale_leases() -> None:
    """
    nothing else recovers a remote-held job - auto-resume on startup
    skips them - so without this a crashed worker's job stays running
    forever. A stale job already carrying stop_requested is deleted
    rather than requeued: it was cancelled before the worker died.
    """
    stale_before = _now() - STALE_LEASE_SECONDS
    stale_jobs = DownscaleInteract.get_stale_leases(stale_before)
    if not stale_jobs:
        return

    for job in stale_jobs:
        doc_id = job["id"]
        tmp_path = job.get("tmp_file_path")

        if job.get("stop_requested"):
            _cleanup_tmp_files(tmp_path)
            DownscaleInteract(doc_id).delete_item()
            continue

        # the tmp file belongs to the expired lease, not to whoever
        # claims this next
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

    dispatch_pending_downscales()
