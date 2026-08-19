"""
functionality:
- claim/heartbeat/result/finish/fail/delete for remote downscale workers

See docs/remote-downscale/ta-server.md. A remote-held job is
status="running" with worker set and task_id="" - it has no celery task,
so none of this goes through TaskCommand/TaskManager the way the local
runner does. Every job-scoped operation re-checks that the doc is still
running and still held by the calling worker before touching it, so a
reaped/requeued/reclaimed job safely rejects a late call from the worker
that used to hold it (the caller turns that into a 409).
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

# suggested worker heartbeat cadence is 10s (worker.md); a lease is
# considered stale - and reapable - once it's gone three heartbeats
# without a renewal
STALE_LEASE_SECONDS = 60

NOT_HELD_ERROR = "job no longer held by this worker"
CANCELLED_ERROR = "job was cancelled"


def _own_job(doc_id: str, worker: str) -> tuple[dict | None, str | None]:
    """
    fetch a job doc and verify it's running and held by this worker.
    returns (job, None) on success, (None, error) when the caller should
    reject the request - the doc is gone, or no longer belongs to this
    worker (reaped/requeued/claimed by someone else)
    """
    job, status_code = DownscaleInteract(doc_id).get_item()
    if status_code == 404 or not job:
        return None, "job not found"

    if job.get("status") != "running" or job.get("worker") != worker:
        return None, NOT_HELD_ERROR

    return job, None


def _cleanup_tmp_files(tmp_path: str | None) -> None:
    """remove a job's finished and in-progress-upload tmp files, if present"""
    if not tmp_path:
        return

    for path in (tmp_path, f"{tmp_path}.part"):
        if os.path.exists(path):
            os.remove(path)


def _discard(doc_id: str, tmp_path: str | None) -> None:
    """
    delete a job's doc and any tmp/part files it produced, then
    dispatch - clearing an active job may free a concurrency slot or
    unblock a different queued job for the same video. Shared by
    delete() and the stop_requested short-circuit in finish()/fail()
    """
    _cleanup_tmp_files(tmp_path)
    DownscaleInteract(doc_id).delete_item()
    dispatch_pending_downscales()


def claim(worker: str) -> dict | None:
    """
    claim the oldest claimable queued job for a remote worker, under the
    same dispatch lock local celery dispatch uses - first claim wins.
    Runs the same validations the local runner performs in run()/
    _reserve_slot() before it starts encoding; invalid candidates are
    failed/deleted and skipped in favor of the next one. Returns the
    claim response dict, or None if nothing is claimable.
    """
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
    """
    validate a single queued candidate and claim it if valid. On any
    invalid condition the doc is failed/deleted exactly as the local
    runner would and None is returned so the caller moves on
    """
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
        # the plain nginx-served static path, not a job-scoped API
        # endpoint: Django's FileResponse over the ASGI/uvicorn worker
        # pool was found to retain the full file size in the serving
        # process's memory (confirmed live, not reclaimable, via
        # malloc_trim) for as long as that worker process runs, with no
        # such growth when nginx serves the same bytes directly via its
        # /youtube/ alias. Ownership isn't checked here the way the old
        # job-scoped endpoint checked it - the same file is already
        # reachable by any authenticated user through the normal
        # download path regardless of job state, so that check was
        # never a real access boundary, just an incidental side effect
        # of routing through a job-scoped view.
        "source_url": f"/youtube/{video.json_data['media_url']}",
    }


def heartbeat(
    doc_id: str, worker: str, progress: float
) -> tuple[dict | None, str | None]:
    """
    renew a job's lease and record progress. Returns a {"stop": bool}
    response on success, matching stop_requested on the doc
    """
    job, error = _own_job(doc_id, worker)
    if error:
        return None, error

    DownscaleInteract(doc_id).update(last_heartbeat=_now(), progress=progress)
    return {"stop": bool(job.get("stop_requested"))}, None


def upload_result(doc_id: str, worker: str, stream) -> str | None:
    """
    stream the uploaded result to <tmp_file_path>.part and rename into
    place only once the full body has been received, so a connection
    drop mid-upload never leaves something that looks like a finished
    file behind. tmp_file_path is deterministic (same video + target
    height reuse the same path across claims), so a worker whose lease
    got reaped-and-reclaimed mid-upload could otherwise land its rename
    on top of whatever a new claim already produced - a large upload
    with no heartbeat traffic of its own can run long enough for that.
    Re-checking ownership immediately before the rename can't close
    that window entirely (two independent renames of the same path is
    inherent to two processes touching it at all), but narrows it from
    "the whole upload" down to a couple of ES round-trips, and catches
    a cancel that arrived mid-upload before it can reach finish()
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
    rename the uploaded file to the container the worker actually
    produced, returning the path it now lives at.

    tmp_file_path is decided once, at enqueue time
    (queue_interact.build_queued_doc), with a hardcoded .mp4 suffix -
    before it's known whether a local celery encode or a remote worker
    will run the job. A remote worker may well produce .mkv instead
    (see worker.md's "Output container"), and nothing between claim and
    here would otherwise notice: upload_result() streams the body onto
    that same fixed path, so the doc ends up advertising a .mp4 path
    for a file that is really MKV, all the way through pending_review
    and into accept(). Correcting it here - the first point the real
    output's container is known - means the persisted tmp_file_path
    describes the bytes on disk for the whole review window, and
    DownscaleReview.accept()'s container matching has something real to
    match on.
    """
    if not container:
        return tmp_path

    # container is validated as bare alphanumerics by
    # WorkerFinishRequestSerializer, so this can only swap the
    # extension - it can never escape the downscale cache dir
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
    mirrors DownscaleRunner._finish_success(): probe the uploaded
    file, mark it pending_review if valid, failed otherwise. Returns an
    error string only for the 409 ownership case - an invalid upload is
    a normal failed job, not a rejected request
    """
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    tmp_path = job["tmp_file_path"]

    if job.get("stop_requested"):
        # cancel arrived after the worker's last heartbeat, in the gap
        # a worker not yet doing concurrent heartbeat-during-upload
        # (see worker.md) has no way to notice - the encode itself is
        # otherwise valid, but the user doesn't want it, so discard
        # rather than surface it for review
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
    """worker reports an encode failure - status=failed, clear worker fields"""
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    if job.get("stop_requested"):
        # already cancelled - discard rather than leave a failed job
        # around for a retry the user never asked for
        _discard(doc_id, job.get("tmp_file_path"))
        return None

    DownscaleInteract(doc_id).update(
        status="failed",
        # same cap the local runner applies to ffmpeg stderr
        # (downscale.py's _encode failure branch)
        message=message[-2000:],
        worker="",
        last_heartbeat=0,
        updated=_now(),
    )
    return None


def delete(doc_id: str, worker: str) -> str | None:
    """
    worker acknowledges a stop request, or abandons a job it can't
    finish for local reasons - deletes the doc, the same end state the
    local cancel path reaches for a queued job
    """
    job, error = _own_job(doc_id, worker)
    if error:
        return error

    _discard(doc_id, job.get("tmp_file_path"))
    return None


def reap_stale_leases() -> None:
    """
    periodic sweep for remote jobs whose lease has gone stale - a
    crashed or powered-off worker never renewed it. Nothing else
    touches a remote-held job on its own (ta_startup's auto-resume
    explicitly skips them, see queue_interact.get_interrupted), so
    without this a dead worker's job would hang in status=running
    forever. A stale job with stop_requested already set is deleted
    instead of requeued - the user cancelled it and the worker just
    never got to acknowledge before it died.
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

        # requeuing back to a fresh queued state - the tmp file (and
        # any leftover in-progress upload) belongs to the lease that
        # just expired, not to whoever claims this next
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
