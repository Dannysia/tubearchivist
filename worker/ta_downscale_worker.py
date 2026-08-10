#!/usr/bin/env python3
"""
TubeArchivist remote downscale worker.

Standalone sister app for a machine with a fast hardware encoder (e.g. an
RTX 5090 running NVENC on Windows). Polls TA's worker API for the oldest
queued downscale job, downloads the source, encodes it locally with the
configured encoder, uploads the result, and reports completion. TA is the
single source of truth for the queue; this script keeps no state between
loop iterations.

See docs/remote-downscale/worker.md for the full design and
docs/remote-downscale/ta-server.md for the API this script consumes.

Only third-party dependency: requests. Config parsing uses the stdlib
tomllib (Python 3.11+, read-only), so no toml library is needed either.
"""

import argparse
import os
import shlex
import subprocess
import threading
import time
import tomllib
from datetime import datetime
from urllib.parse import urljoin

import requests

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB, source-download streaming reads

# "a couple of lease periods" (worker.md) - the server's own stale-lease
# threshold is 60s (STALE_LEASE_SECONDS in downscale/src/worker.py); a
# network call that keeps failing past this window is abandoned rather
# than retried forever, since the server will have reaped the lease
# anyway by the time this elapses.
NETWORK_RETRY_ABANDON_SECONDS = 120


class WorkerAbandon(Exception):
    """
    raised to unwind out of the current job and move on to the next
    claim. Covers lease loss (409 conflict - "409 means abandon, never
    retry" in worker.md), an explicit stop request (ack=True: the worker
    owes the server a DELETE to acknowledge it), and a network outage
    that outlasts the bounded retry window.
    """

    def __init__(self, reason: str, ack: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.ack = ack


class _UploadAborted(Exception):
    """
    raised by _AbortableFile when the concurrent heartbeat has flagged a
    stop/conflict mid-upload. Caught locally inside upload_result();
    handle_job() checks pulse.aborted right after to unwind with the
    correct reason/ack, so this class carries no information of its own.
    """


def log(message: str) -> None:
    """
    console output is the only observability on the worker side (no
    server-side visibility into a remote box) - one line per state
    change, per worker.md
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


# --------------------------------------------------------------------------
# config


def load_config(path: str) -> dict:
    """load and validate worker.toml, filling in documented defaults"""
    with open(path, "rb") as config_file:
        config = tomllib.load(config_file)

    server = config.setdefault("server", {})
    worker = config.setdefault("worker", {})
    encode = config.setdefault("encode", {})

    required = [
        (server, "server", "url"),
        (server, "server", "token"),
        (worker, "worker", "name"),
        (worker, "worker", "temp_dir"),
        (encode, "encode", "ffmpeg_path"),
        (encode, "encode", "encoder"),
    ]
    for section, section_name, key in required:
        if not section.get(key):
            raise SystemExit(f"worker.toml: missing [{section_name}] {key}")

    worker.setdefault("poll_interval", 30)
    worker.setdefault("heartbeat_interval", 10)
    encode.setdefault("preset", None)
    encode.setdefault("cq", 30)
    encode.setdefault("extra_args", [])

    return config


def build_session(config: dict) -> requests.Session:
    """DRF token auth, same as any other TA API client"""
    session = requests.Session()
    session.headers["Authorization"] = f"Token {config['server']['token']}"
    return session


# --------------------------------------------------------------------------
# WSL / ffmpeg path handling


def _is_wsl() -> bool:
    if os.name != "posix":
        return False
    try:
        with open("/proc/version", "r", encoding="utf-8") as version_file:
            return "microsoft" in version_file.read().lower()
    except OSError:
        return False


_IS_WSL = _is_wsl()


def _ffmpeg_path_arg(path: str) -> str:
    """
    convert a POSIX path to the Windows-style path ffmpeg.exe/ffprobe.exe
    expect, when this script runs under WSL invoking Windows binaries
    directly - see worker.md "Windows/WSL specifics". A no-op under
    native Windows Python, where paths are already Windows-style.
    """
    if not _IS_WSL:
        return path
    result = subprocess.run(
        ["wslpath", "-w", path], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _sibling_binary(ffmpeg_path: str, name: str) -> str:
    """
    derive ffprobe's path from the configured ffmpeg_path by swapping the
    binary name, keeping the same directory/extension - gyan.dev and
    BtbN Windows builds ship both side by side. Override via
    encode.ffprobe_path in worker.toml if that assumption doesn't hold.

    ffmpeg_path may be a Windows-style path ("C:\\ffmpeg\\bin\\ffmpeg.exe")
    even when this script runs under WSL's POSIX Python, where
    os.path.split only recognizes "/" - splitting on that alone would
    treat the whole backslash-separated string as one filename and
    replace "ffmpeg" everywhere in it, not just the basename. Split on
    whichever separator actually appears last instead.
    """
    split_at = max(ffmpeg_path.rfind("/"), ffmpeg_path.rfind("\\")) + 1
    directory, filename = ffmpeg_path[:split_at], ffmpeg_path[split_at:]
    return directory + filename.replace("ffmpeg", name)


# --------------------------------------------------------------------------
# ffmpeg


def build_ffmpeg_cmd(
    config: dict, src_path: str, out_path: str, target_height: int
) -> list[str]:
    """
    mirrors what TA builds locally (_build_ffmpeg_cmd), with the encoder
    block swapped for whatever this worker is configured to use - see
    worker.md "The ffmpeg command"
    """
    encode = config["encode"]
    cmd = [
        encode["ffmpeg_path"],
        "-y",
        "-i",
        _ffmpeg_path_arg(src_path),
        "-vf",
        f"scale=-2:{target_height}",
        "-c:v",
        encode["encoder"],
    ]
    if encode.get("preset"):
        cmd += ["-preset", str(encode["preset"])]
    cmd += ["-rc", "vbr", "-cq", str(encode["cq"]), "-b:v", "0"]
    cmd += [str(arg) for arg in encode.get("extra_args", [])]
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
        _ffmpeg_path_arg(out_path),
    ]
    return cmd


def probe_duration(config: dict, src_path: str) -> float | None:
    """
    duration for progress comes from probing the downloaded source
    rather than trusting metadata from TA - one less field in the API,
    and it's the file actually being encoded. None on failure just means
    degraded progress reporting (pinned near 0 until the upload phase),
    not a fatal error.
    """
    ffprobe_path = config["encode"].get("ffprobe_path") or _sibling_binary(
        config["encode"]["ffmpeg_path"], "ffprobe"
    )
    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrapper=1:nokey=1",
        _ffmpeg_path_arg(src_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=True
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        log(f"could not probe source duration: {exc}")
        return None


def _parse_ffmpeg_time(value: str) -> float | None:
    """parse ffmpeg -progress's out_time value, "HH:MM:SS.ffffff" """
    try:
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, AttributeError):
        return None


def _read_progress(proc: subprocess.Popen, duration, progress_state: dict):
    """
    background reader for ffmpeg's -progress pipe:1 output. Progress is
    capped at 0.99 here - 1.0 is reserved for the upload/finish phase, so
    a viewer never sees "100%" while the file is still being written
    """
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time" and duration:
            seconds = _parse_ffmpeg_time(value)
            if seconds is not None:
                progress_state["fraction"] = max(
                    0.0, min(seconds / duration, 0.99)
                )


def _read_stderr(proc: subprocess.Popen, tail: list[str]) -> None:
    """
    background reader for ffmpeg's stderr, kept as a rolling tail for a
    fail() report. Read on its own thread (not just stdout) so ffmpeg
    never blocks on a full stderr pipe while nothing is draining it
    """
    for line in proc.stderr:
        tail.append(line)
        while len(tail) > 1 and sum(len(chunk) for chunk in tail) > 4000:
            tail.pop(0)


def spawn_ffmpeg(cmd: list[str], duration: float | None):
    """start ffmpeg and its progress/stderr reader threads"""
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    progress_state = {"fraction": 0.0}
    stderr_tail: list[str] = []
    threading.Thread(
        target=_read_progress,
        args=(proc, duration, progress_state),
        daemon=True,
    ).start()
    threading.Thread(
        target=_read_stderr, args=(proc, stderr_tail), daemon=True
    ).start()
    return proc, progress_state, stderr_tail


# --------------------------------------------------------------------------
# TA API calls


def _call_with_backoff(fn, description: str):
    """
    retry fn() with exponential backoff for up to
    NETWORK_RETRY_ABANDON_SECONDS on a network blip
    (requests.RequestException) before giving up with WorkerAbandon -
    "network blips != job failure" in worker.md. fn() raising anything
    else (WorkerAbandon for a 409, in particular) is not a network blip
    and passes straight through unretried.
    """
    delay = 1.0
    deadline = time.monotonic() + NETWORK_RETRY_ABANDON_SECONDS
    while True:
        try:
            return fn()
        except requests.RequestException as exc:
            if time.monotonic() >= deadline:
                raise WorkerAbandon("network") from exc
            log(f"{description} failed ({exc}), retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 30)


def claim(session, base_url, worker_name, encoders) -> dict | None:
    """
    claim the oldest claimable job, or None if there's nothing to claim
    or the request itself failed - either way just means "try again next
    poll", no lease is held yet so there's nothing to abandon
    """
    url = urljoin(base_url, "/api/downscale/worker/claim/")
    body = {"worker": worker_name, "encoders": encoders}
    try:
        resp = session.post(url, json=body, timeout=(10, 30))
    except requests.RequestException as exc:
        log(f"claim failed: {exc}")
        return None
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    return resp.json()


def download_source(session, base_url, worker_name, job, dest_path) -> None:
    """GET the source file, worker identity via X-TA-Worker (no JSON body)"""
    url = urljoin(base_url, job["source_url"])

    def _attempt():
        resp = session.get(
            url,
            headers={"X-TA-Worker": worker_name},
            stream=True,
            timeout=(10, 60),
        )
        if resp.status_code == 409:
            raise WorkerAbandon("conflict")
        resp.raise_for_status()
        return resp

    resp = _call_with_backoff(
        _attempt, f"download source for {job['youtube_id']}"
    )
    with open(dest_path, "wb") as dest_file:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            dest_file.write(chunk)


def _post_heartbeat(
    session, base_url, worker_name, job_id, progress
) -> tuple[bool, bool]:
    """POST heartbeat, returns (stop, conflict)"""
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/heartbeat/")
    resp = session.post(
        url,
        json={"worker": worker_name, "progress": progress},
        timeout=(10, 30),
    )
    if resp.status_code == 409:
        return False, True
    resp.raise_for_status()
    return bool(resp.json().get("stop")), False


class LeaseHeartbeat:
    """
    background thread that renews a claimed job's lease at a fixed
    cadence while the main thread is busy encoding or uploading.
    Encoding and upload/finish can each run far longer than
    heartbeat_interval, so without this the server's stale-lease reaper
    could reclaim a job that is still very much in progress - see
    worker.md "Rules that make this robust". The main thread polls
    .aborted rather than being interrupted, since it may be blocked in a
    subprocess wait or a streaming upload read.
    """

    def __init__(
        self, session, base_url, worker_name, job_id, interval, progress_fn
    ):
        self._session = session
        self._base_url = base_url
        self._worker_name = worker_name
        self._job_id = job_id
        self._interval = interval
        self._progress_fn = progress_fn
        self._stop_event = threading.Event()
        self.abort_reason: str | None = None
        self.ack = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """ask the thread to exit once the job is done with it"""
        self._stop_event.set()
        self._thread.join(timeout=self._interval + 5)

    @property
    def aborted(self) -> bool:
        return self.abort_reason is not None

    def _run(self) -> None:
        failure_since: float | None = None
        while not self._stop_event.wait(self._interval):
            try:
                stop, conflict = _post_heartbeat(
                    self._session,
                    self._base_url,
                    self._worker_name,
                    self._job_id,
                    self._progress_fn(),
                )
            except requests.RequestException as exc:
                failure_since = failure_since or time.monotonic()
                if (
                    time.monotonic() - failure_since
                    > NETWORK_RETRY_ABANDON_SECONDS
                ):
                    log(f"heartbeat network failure, abandoning: {exc}")
                    self.abort_reason = "network"
                    return
                continue
            failure_since = None
            if conflict:
                self.abort_reason = "conflict"
                return
            if stop:
                self.abort_reason = "cancelled"
                self.ack = True
                return


class _AbortableFile:
    """
    file-like wrapper read by requests during PUT result/ - sets
    Content-Length via __len__ (a plain, non-chunked upload; a WSGI
    server can't be assumed to support chunked request bodies) while
    still checking the concurrent heartbeat on every read() call, so a
    cancel or lease loss detected mid-upload aborts the transfer in
    flight rather than only being noticed after the whole file lands -
    see worker.md's rationale for heartbeating through this phase.
    """

    def __init__(self, path: str, pulse: LeaseHeartbeat):
        self._file = open(path, "rb")  # pylint: disable=consider-using-with
        self._pulse = pulse
        self._size = os.fstat(self._file.fileno()).st_size

    def __len__(self) -> int:
        return self._size

    def read(self, size: int = -1) -> bytes:
        if self._pulse.aborted:
            raise _UploadAborted()
        return self._file.read(size)

    def close(self) -> None:
        self._file.close()


def upload_result(
    session, base_url, worker_name, job_id, path, pulse: LeaseHeartbeat
) -> None:
    """
    PUT the encoded result. Ownership is re-checked server-side
    immediately before the rename regardless of what this function
    detects, so an imperfect local abort is a responsiveness concern for
    cancel, not a correctness one - see ta-server.md's PUT result/
    section.
    """
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/result/")

    def _attempt():
        body = _AbortableFile(path, pulse)
        try:
            resp = session.put(
                url,
                data=body,
                headers={
                    "X-TA-Worker": worker_name,
                    "Content-Type": "application/octet-stream",
                },
                timeout=(10, None),
            )
        finally:
            body.close()
        if resp.status_code == 409:
            raise WorkerAbandon("conflict")
        resp.raise_for_status()

    try:
        _call_with_backoff(_attempt, f"upload result for job {job_id}")
    except _UploadAborted:
        pass  # pulse already recorded why; handle_job checks pulse.aborted


def send_finish(
    session,
    base_url,
    worker_name,
    job_id,
    encoder,
    quality,
    preset,
    ffmpeg_args,
) -> None:
    """POST finish, reporting what was actually run"""
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/finish/")

    def _attempt():
        resp = session.post(
            url,
            json={
                "worker": worker_name,
                "encoder": encoder,
                "quality": quality,
                "preset": preset,
                "ffmpeg_args": ffmpeg_args,
            },
            timeout=(10, 30),
        )
        if resp.status_code == 409:
            raise WorkerAbandon("conflict")
        resp.raise_for_status()

    _call_with_backoff(_attempt, f"finish for job {job_id}")


def report_fail(session, base_url, worker_name, job_id, message) -> None:
    """
    POST fail, best-effort - if this itself can't get through, there's
    nothing more useful to do than log and move on; the job is left
    running server-side until the reaper eventually requeues it
    """
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/fail/")

    def _attempt():
        resp = session.post(
            url,
            json={"worker": worker_name, "message": message},
            timeout=(10, 30),
        )
        if resp.status_code == 409:
            return  # already reaped/cancelled, nothing to report
        resp.raise_for_status()

    try:
        _call_with_backoff(_attempt, f"report failure for job {job_id}")
    except WorkerAbandon:
        log(f"could not report failure for job {job_id}, giving up")


def try_delete(session, base_url, worker_name, job_id) -> None:
    """
    best-effort acknowledgement of a stop request. No retry: if this
    doesn't land, the reaper's stop_requested branch cleans up once the
    lease goes stale - see worker.md's cancel handling.
    """
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/")
    try:
        session.delete(
            url, headers={"X-TA-Worker": worker_name}, timeout=(10, 30)
        )
    except requests.RequestException as exc:
        log(f"could not delete/ack job {job_id}: {exc}")


# --------------------------------------------------------------------------
# temp files


def sweep_temp_dir(temp_dir: str) -> None:
    """
    crash-safe by construction: all state lives on the server, so on
    startup any leftover file from a previous crash is just discarded
    """
    os.makedirs(temp_dir, exist_ok=True)
    removed = 0
    for name in os.listdir(temp_dir):
        path = os.path.join(temp_dir, name)
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
    if removed:
        log(f"swept {removed} leftover file(s) from {temp_dir}")


def cleanup_job_temp(temp_dir: str, youtube_id: str, target_height: int):
    for path in (
        os.path.join(temp_dir, f"{youtube_id}.src"),
        os.path.join(temp_dir, f"{youtube_id}_{target_height}p.out.mp4"),
    ):
        if os.path.exists(path):
            os.remove(path)


# --------------------------------------------------------------------------
# one job


def handle_job(job: dict, session, base_url: str, config: dict) -> None:
    """
    run one claimed job through encode -> upload -> finish. Returns
    normally on success; raises WorkerAbandon on any cancel/conflict/
    network-exhaustion path. A local ffmpeg failure is reported via
    fail() and also returns normally - it's a completed job outcome, not
    an abandon.
    """
    worker_name = config["worker"]["name"]
    heartbeat_interval = config["worker"]["heartbeat_interval"]
    temp_dir = config["worker"]["temp_dir"]
    job_id = job["id"]
    youtube_id = job["youtube_id"]
    target_height = job["target_height"]

    log(f"claimed {youtube_id} -> {target_height}p")

    src_path = os.path.join(temp_dir, f"{youtube_id}.src")
    out_path = os.path.join(temp_dir, f"{youtube_id}_{target_height}p.out.mp4")
    download_source(session, base_url, worker_name, job, src_path)

    duration = probe_duration(config, src_path)
    cmd = build_ffmpeg_cmd(config, src_path, out_path, target_height)
    ffmpeg_args = shlex.join(cmd)
    log(f"encoding {youtube_id}: {ffmpeg_args}")

    proc, progress_state, stderr_tail = spawn_ffmpeg(cmd, duration)
    pulse = LeaseHeartbeat(
        session,
        base_url,
        worker_name,
        job_id,
        heartbeat_interval,
        progress_fn=lambda: progress_state["fraction"],
    )
    pulse.start()
    try:
        while proc.poll() is None:
            if pulse.aborted:
                proc.kill()
                proc.wait(timeout=10)
                raise WorkerAbandon(pulse.abort_reason, ack=pulse.ack)
            time.sleep(0.5)
    finally:
        pulse.stop()

    if proc.returncode != 0:
        message = "".join(stderr_tail)[-2000:]
        log(f"ffmpeg failed ({proc.returncode}) for {youtube_id}")
        report_fail(session, base_url, worker_name, job_id, message)
        return

    log(f"encoded {youtube_id}, uploading")
    pulse = LeaseHeartbeat(
        session,
        base_url,
        worker_name,
        job_id,
        heartbeat_interval,
        progress_fn=lambda: 1.0,
    )
    pulse.start()
    try:
        upload_result(session, base_url, worker_name, job_id, out_path, pulse)
        if pulse.aborted:
            raise WorkerAbandon(pulse.abort_reason, ack=pulse.ack)

        log(f"finishing {youtube_id}")
        send_finish(
            session,
            base_url,
            worker_name,
            job_id,
            config["encode"]["encoder"],
            config["encode"]["cq"],
            config["encode"].get("preset"),
            ffmpeg_args,
        )
    finally:
        pulse.stop()


# --------------------------------------------------------------------------
# main loop


def main() -> None:
    default_config = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worker.toml"
    )
    parser = argparse.ArgumentParser(
        description="TubeArchivist remote downscale worker"
    )
    parser.add_argument(
        "--config",
        default=default_config,
        help="path to worker.toml (default: next to this script)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    session = build_session(config)
    base_url = config["server"]["url"]
    worker_name = config["worker"]["name"]
    temp_dir = config["worker"]["temp_dir"]

    sweep_temp_dir(temp_dir)
    log(f"worker '{worker_name}' starting, polling {base_url}")

    while True:
        job = claim(
            session, base_url, worker_name, [config["encode"]["encoder"]]
        )
        if job is None:
            time.sleep(config["worker"]["poll_interval"])
            continue

        youtube_id = job["youtube_id"]
        try:
            handle_job(job, session, base_url, config)
            log(f"done: {youtube_id}")
        except WorkerAbandon as exc:
            log(f"abandoned {youtube_id} ({exc.reason})")
            if exc.ack:
                try_delete(session, base_url, worker_name, job["id"])
        except Exception as exc:  # pylint: disable=broad-except
            # a single job's failure must never kill the worker loop -
            # crash-safe by construction (worker.md): the server reaps
            # the stale lease and requeues the job either way
            log(f"unexpected error on {youtube_id}, abandoning: {exc}")
        finally:
            cleanup_job_temp(temp_dir, youtube_id, job["target_height"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log("stopping")
