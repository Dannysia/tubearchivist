#!/usr/bin/env python3
"""
TubeArchivist remote downscale worker.

Standalone sister app for a machine with a fast hardware encoder: polls
TA's worker API for the oldest queued downscale job, downloads the
source, encodes it, uploads the result, reports completion. TA holds all
queue state; this script keeps none between iterations.

Encoding goes through HandBrakeCLI rather than ffmpeg directly because
HandBrake preserves HDR10 static metadata through an NVENC re-encode;
ffmpeg then stream-copies that into the MP4 TA stores, and ffprobe
checks what survived. Third-party Python dependency: requests.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import threading
import time
import tomllib
from datetime import datetime
from urllib.parse import urljoin

import requests

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB

# two of the server's 60s stale-lease periods: a call still failing past
# this window has lost the lease anyway
NETWORK_RETRY_ABANDON_SECONDS = 120

# a stream copy runs at disk speed, so this is a "something is wedged"
# backstop: a 20 GB remux over a slow disk still lands well inside it
REMUX_TIMEOUT = 1800

# HandBrake encodes to MKV because it writes HDR10 static metadata only
# at the container level under NVENC, not into the bitstream, and MKV is
# the container that behaviour is documented for. The result is remuxed
# to MP4 because TA is MP4-only well beyond this feature - the
# filesystem scanner only sees *.mp4, and deletes indexed videos it
# can't see - so an .mkv means silent, permanent media loss. The remux
# is a stream copy, so it costs no quality.
ENCODE_CONTAINER = "mkv"
OUTPUT_CONTAINER = "mp4"


class WorkerAbandon(Exception):
    """
    unwind out of the current job and claim the next one.

    ack=True means the server is owed a DELETE acknowledging a stop
    request. fail_message means the job should end failed with that
    reason rather than be silently reaped and requeued.
    """

    def __init__(
        self,
        reason: str,
        ack: bool = False,
        fail_message: str | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.ack = ack
        self.fail_message = fail_message


class _UploadAborted(Exception):
    """
    carries no information of its own: pulse.aborted holds the reason
    the upload was cut short.
    """


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def load_config(path: str) -> dict:
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
        (encode, "encode", "handbrake_path"),
        (encode, "encode", "encoder"),
    ]
    for section, section_name, key in required:
        if not section.get(key):
            raise SystemExit(f"worker.toml: missing [{section_name}] {key}")

    worker.setdefault("poll_interval", 30)
    worker.setdefault("heartbeat_interval", 10)
    encode.setdefault("preset", None)
    encode.setdefault("tune", None)
    encode.setdefault("quality", 30)
    encode.setdefault("extra_args", [])

    # HandBrake takes a fractional -q, but TA stores quality as an
    # integer and its finish endpoint rejects anything else - caught
    # here rather than as a 400 after a whole job has been encoded.
    if isinstance(encode["quality"], bool) or not isinstance(
        encode["quality"], int
    ):
        raise SystemExit(
            "worker.toml: [encode] quality must be a whole number "
            f"(got {encode['quality']!r}) - TA records it as an integer"
        )

    return config


def build_session(config: dict) -> requests.Session:
    session = requests.Session()
    session.headers["Authorization"] = f"Token {config['server']['token']}"
    return session


def _is_wsl() -> bool:
    if os.name != "posix":
        return False
    try:
        with open("/proc/version", "r", encoding="utf-8") as version_file:
            return "microsoft" in version_file.read().lower()
    except OSError:
        return False


_IS_WSL = _is_wsl()


def _win_path_arg(path: str) -> str:
    """
    the .exe binaries need a Windows-style path when called from WSL; a
    no-op under native Windows Python, where paths already are one.
    """
    if not _IS_WSL:
        return path
    result = subprocess.run(
        ["wslpath", "-w", path], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _sibling_binary(ffmpeg_path: str, name: str) -> str:
    """
    assumes ffmpeg and ffprobe sit side by side, as the common Windows
    builds ship them; override with encode.ffprobe_path otherwise.

    Splits on the last "/" or "\\" because ffmpeg_path may be a Windows
    path under WSL's POSIX Python, where os.path.split recognizes only
    "/" and would replace "ffmpeg" throughout one long filename.
    """
    split_at = max(ffmpeg_path.rfind("/"), ffmpeg_path.rfind("\\")) + 1
    directory, filename = ffmpeg_path[:split_at], ffmpeg_path[split_at:]
    return directory + filename.replace("ffmpeg", name)


def _ffprobe_path(config: dict) -> str:
    return config["encode"].get("ffprobe_path") or _sibling_binary(
        config["encode"]["ffmpeg_path"], "ffprobe"
    )


# ffprobe reports these as stable human-readable labels, not a numeric
# enum
HDR_STATIC_METADATA_SIDE_DATA_TYPES = {
    "Mastering display metadata",
    "Content light level metadata",
}


def probe_hdr_static_metadata(config: dict, path: str) -> set[str]:
    """
    the types on the first video stream; empty means none present *or*
    the probe failed, which only drives logging either way.

    Stream and frame side data both: container-level metadata (what
    HandBrake writes under NVENC) is reported per stream, while SEI in
    the bitstream (x265, SVT-AV1) is reported only per frame.
    -read_intervals %+#1 parses one frame, so this stays cheap on a
    multi-GB input.
    """
    cmd = [
        _ffprobe_path(config),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_streams",
        "-show_frames",
        "-read_intervals",
        "%+#1",
        "-of",
        "json",
        _win_path_arg(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=True
        )
        probed = json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        log(f"could not probe HDR static metadata: {exc}")
        return set()

    found = set()
    containers = (probed.get("streams") or []) + (probed.get("frames") or [])
    for container in containers:
        for entry in container.get("side_data_list") or []:
            side_data_type = entry.get("side_data_type")
            if side_data_type in HDR_STATIC_METADATA_SIDE_DATA_TYPES:
                found.add(side_data_type)

    return found


def build_remux_cmd(
    config: dict, encoded_path: str, out_path: str
) -> list[str]:
    """
    -c copy is a stream copy: only the container changes, so there is no
    second generation of loss. -map 0:v:0 -map 0:a? drops subtitles,
    which MKV accepts in codecs MP4 has no place for; TA keeps them as
    sidecar .vtt anyway. +faststart puts the moov atom first so playback
    can start before the whole file has been fetched.
    """
    return [
        config["encode"]["ffmpeg_path"],
        "-v",
        "error",
        "-y",
        "-i",
        _win_path_arg(encoded_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        _win_path_arg(out_path),
    ]


def run_remux(
    config: dict, encoded_path: str, out_path: str
) -> tuple[bool, str]:
    """returns (ok, error_output)"""
    cmd = build_remux_cmd(config, encoded_path, out_path)
    log(f"remuxing: {shlex.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=REMUX_TIMEOUT
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"remux to {OUTPUT_CONTAINER} failed to run: {exc}"

    if result.returncode != 0:
        return False, f"remux exited {result.returncode}: {result.stderr}"

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        return False, "remux produced no output"

    return True, ""


def log_hdr_metadata_outcome(
    config: dict, youtube_id: str, encoded_path: str, out_path: str
) -> None:
    """
    whether a stream copy reproduces HandBrake's container-level HDR10
    metadata as MP4 mdcv/clli boxes depends on the ffmpeg build and the
    encoder, so probe both files rather than assume.
    """
    encoded_hdr = probe_hdr_static_metadata(config, encoded_path)
    if not encoded_hdr:
        return

    final_hdr = probe_hdr_static_metadata(config, out_path)
    if final_hdr >= encoded_hdr:
        log(
            f"{youtube_id}: HDR10 static metadata survived the remux "
            f"({', '.join(sorted(final_hdr))})"
        )
        return

    log(
        f"{youtube_id}: WARNING - HDR10 static metadata lost in the remux "
        f"to {OUTPUT_CONTAINER}: {', '.join(sorted(encoded_hdr - final_hdr))}"
        " - see docs/remote-downscale/windows-host-setup.md"
    )


def build_handbrake_cmd(
    config: dict, src_path: str, out_path: str, target_height: int
) -> list[str]:
    """
    --non-anamorphic with only --height set is HandBrake's scale=-2:H:
    it forces 1:1 pixels, which is what makes an unset --width
    auto-compute proportionally instead of keeping the source's.

    NOT --keep-display-aspect: that only takes effect under
    --custom-anamorphic, and alone it left storage width at the
    source's 3840 and faked the display size with a 1:3 pixel aspect
    ratio instead of downscaling.
    """
    encode = config["encode"]
    cmd = [
        encode["handbrake_path"],
        "-i",
        _win_path_arg(src_path),
        "-o",
        _win_path_arg(out_path),
        "-e",
        encode["encoder"],
        "-q",
        str(encode["quality"]),
        "--height",
        str(target_height),
        "--non-anamorphic",
    ]
    if encode.get("preset"):
        cmd += ["--encoder-preset", str(encode["preset"])]
    if encode.get("tune"):
        cmd += ["--encoder-tune", str(encode["tune"])]
    cmd += [str(arg) for arg in encode.get("extra_args", [])]
    return cmd


# HandBrakeCLI's console progress line, e.g.:
#   "Encoding: task 1 of 1, 45.23 % (123.45 fps, avg 120.00 fps, ETA ...)"
# different wording just leaves progress at 0
_HANDBRAKE_PROGRESS_RE = re.compile(r"task \d+ of \d+, (\d+(?:\.\d+)?)\s*%")


def _read_handbrake_output(
    proc: subprocess.Popen, progress_state: dict, tail: list[str]
) -> None:
    """
    stdout and stderr are merged because HandBrakeCLI's split of
    progress vs. logging between them isn't documented. Progress caps
    at 0.99; 1.0 is reserved for the upload/finish phase.

    Line iteration is enough despite progress repainting in place with
    \\r: the pipe is in text mode, and universal-newline translation
    turns a bare \\r into \\n before the iterator sees it.
    """
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue

        tail.append(line + "\n")
        while len(tail) > 1 and sum(len(c) for c in tail) > 4000:
            tail.pop(0)

        match = _HANDBRAKE_PROGRESS_RE.search(line)
        if match:
            percent = float(match.group(1))
            progress_state["fraction"] = max(0.0, min(percent / 100, 0.99))


def spawn_handbrake(cmd: list[str], progress_state: dict):
    """
    the reader thread writes encode progress into progress_state, which
    the job's LeaseHeartbeat reads from concurrently.
    """
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output_tail: list[str] = []
    threading.Thread(
        target=_read_handbrake_output,
        args=(proc, progress_state, output_tail),
        daemon=True,
    ).start()
    return proc, output_tail


def _permanent_http_status(exc: Exception) -> int | None:
    """
    the status code when the server will keep returning the same
    rejection, else None. 408 and 429 mean "try again", so they stay
    retryable along with every 5xx. 409 never arrives here - it is
    checked for before raise_for_status.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None

    status = response.status_code
    if 400 <= status < 500 and status not in (408, 429):
        return status

    return None


def _http_error_detail(exc: Exception, status: int) -> str:
    """
    DRF puts the actual validation error in the response body, which is
    the only thing that makes a rejection diagnosable afterwards
    """
    response = getattr(exc, "response", None)
    body = ""
    if response is not None:
        try:
            body = " ".join(response.text.split())[:500]
        except (ValueError, UnicodeError):
            body = ""

    return f"HTTP {status}: {body}" if body else f"HTTP {status}"


def _call_with_backoff(fn, description: str):
    """
    only requests.RequestException is retried; anything else, a 409's
    WorkerAbandon in particular, passes straight through. A 4xx other
    than 409 is a rejection of the request itself, so it abandons at
    once rather than burning the retry window on an identical payload.
    """
    delay = 1.0
    deadline = time.monotonic() + NETWORK_RETRY_ABANDON_SECONDS
    while True:
        try:
            return fn()
        except requests.RequestException as exc:
            status = _permanent_http_status(exc)
            if status:
                detail = _http_error_detail(exc, status)
                log(f"{description} rejected with {detail}")
                raise WorkerAbandon(
                    f"http {status}",
                    fail_message=f"TA rejected {description} - {detail}",
                ) from exc
            if time.monotonic() >= deadline:
                raise WorkerAbandon("network") from exc
            log(f"{description} failed ({exc}), retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 30)


def claim(session, base_url, worker_name, encoders) -> dict | None:
    """
    None means nothing to claim *or* the request failed: no lease is
    held either way, so there is nothing to abandon
    """
    url = urljoin(base_url, "/api/downscale/worker/claim/")
    body = {"worker": worker_name, "encoders": encoders}
    try:
        resp = session.post(url, json=body, timeout=(10, 30))
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        # HTTPError and JSONDecodeError are both RequestException
        # subclasses, so a bad status or a garbled body lands here too.
        # Nothing may escape: this runs outside the per-job handler.
        log(f"claim failed: {exc}")
        return None


def download_source(session, base_url, job, dest_path) -> None:
    """
    source_url is a plain nginx-served static path, not a job-scoped
    API endpoint, so nothing here checks job ownership and no 409 can
    come back. Auth is still required, via the session header.
    """
    url = urljoin(base_url, job["source_url"])

    def _attempt():
        resp = session.get(url, stream=True, timeout=(10, 60))
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
    renews a claimed job's lease while the main thread encodes or
    uploads, either of which outlasts heartbeat_interval and would let
    the server's reaper reclaim a job still in progress. The main
    thread polls .aborted rather than being interrupted, since it may
    be blocked in a subprocess wait or a streaming upload read.
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
                # a refused request won't start being accepted, so
                # don't spend the whole retry window on it. No
                # fail_message: a refused heartbeat points at a
                # worker-wide problem, not at this job, so letting it
                # requeue is right.
                status = _permanent_http_status(exc)
                if status:
                    log(f"heartbeat rejected with HTTP {status}, abandoning")
                    self.abort_reason = f"http {status}"
                    return

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
    __len__ sets Content-Length, keeping this a non-chunked upload: a
    WSGI server can't be assumed to accept a chunked request body.
    read() checks the concurrent heartbeat, so a cancel or lease loss
    aborts the transfer in flight instead of after the file lands.
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
    the server re-checks ownership immediately before its rename, so an
    imperfect local abort costs cancel responsiveness, not correctness.
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
        pass  # the caller checks pulse.aborted, which holds the reason


def send_finish(
    session,
    base_url,
    worker_name,
    job_id,
    encoder,
    quality,
    preset,
    encode_args,
    container,
) -> None:
    """
    the server's ffmpeg_args field holds whatever encode command
    actually ran - a HandBrakeCLI one here.

    container is the bare extension actually produced. TA fixes a job's
    tmp_file_path to .mp4 at enqueue time, so without this the server
    keeps calling the uploaded file .mp4 whatever is really in it.
    """
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/finish/")

    def _attempt():
        resp = session.post(
            url,
            json={
                "worker": worker_name,
                "encoder": encoder,
                "quality": quality,
                "preset": preset,
                "ffmpeg_args": encode_args,
                "container": container,
            },
            timeout=(10, 30),
        )
        if resp.status_code == 409:
            raise WorkerAbandon("conflict")
        resp.raise_for_status()

    _call_with_backoff(_attempt, f"finish for job {job_id}")


def report_fail(session, base_url, worker_name, job_id, message) -> None:
    """
    best-effort: if this can't get through, the job is left running
    server-side until the reaper requeues it
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


def report_permanent_failure(
    session, base_url, worker_name, job_id, message
) -> None:
    """
    a request TA rejected will be rejected identically next time, so
    without this the reaper requeues the job and the same video
    re-encodes into the same rejection forever, at full GPU load.

    The broad except is because this runs from inside the main loop's
    own exception handler, where an escape would kill the worker.
    """
    log(f"marking job {job_id} failed: {message}")
    try:
        report_fail(session, base_url, worker_name, job_id, message)
    except Exception as exc:  # pylint: disable=broad-except
        log(
            f"could not mark job {job_id} failed ({exc}) - "
            "leaving it for the server's reaper"
        )


def try_delete(session, base_url, worker_name, job_id) -> None:
    """
    best-effort: no retry, the server's reaper cleans up a cancelled
    job once its lease goes stale.
    """
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/")
    try:
        session.delete(
            url, headers={"X-TA-Worker": worker_name}, timeout=(10, 30)
        )
    except requests.RequestException as exc:
        log(f"could not delete/ack job {job_id}: {exc}")


def sweep_temp_dir(temp_dir: str) -> None:
    """
    all state lives on the server, so any leftover from a previous run
    is discardable. temp_dir must already be this worker's own
    subdirectory, so this never touches a concurrent worker's files. A
    restart can still race its own just-exited process for a file
    handle on Windows, hence the per-file try/except.
    """
    os.makedirs(temp_dir, exist_ok=True)
    removed = 0
    for name in os.listdir(temp_dir):
        path = os.path.join(temp_dir, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed += 1
            except OSError as exc:
                log(f"sweep failed for {path}, leaving for next sweep: {exc}")
    if removed:
        log(f"swept {removed} leftover file(s) from {temp_dir}")


def _job_paths(
    temp_dir: str, youtube_id: str, target_height: int
) -> tuple[str, str, str]:
    """
    three files, not two: the MKV encode and the remuxed MP4 coexist on
    disk until cleanup, so temp_dir needs room for source + encode +
    remux at once.
    """
    src_path = os.path.join(temp_dir, f"{youtube_id}.src")
    base = os.path.join(temp_dir, f"{youtube_id}_{target_height}p.out")
    return src_path, f"{base}.{ENCODE_CONTAINER}", f"{base}.{OUTPUT_CONTAINER}"


def cleanup_job_temp(temp_dir: str, youtube_id: str, target_height: int):
    """
    best-effort: on Windows a file HandBrake or ffmpeg still holds open
    raises PermissionError, and the next startup sweep picks it up.
    """
    for path in _job_paths(temp_dir, youtube_id, target_height):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            log(f"cleanup failed for {path}, leaving for next sweep: {exc}")


def deliver_result(
    job: dict,
    session,
    base_url: str,
    config: dict,
    encoded_path: str,
    out_path: str,
    encode_args: str,
    pulse: "LeaseHeartbeat",
    progress_state: dict,
) -> None:
    """
    progress_state is bumped to 1.0 - the encode caps itself at 0.99 -
    since nothing after it has progress ticks of its own.
    """
    worker_name = config["worker"]["name"]
    job_id = job["id"]
    youtube_id = job["youtube_id"]

    log(f"encoded {youtube_id}, remuxing to {OUTPUT_CONTAINER}")
    progress_state["fraction"] = 1.0

    remuxed, remux_error = run_remux(config, encoded_path, out_path)
    if pulse.aborted:
        raise WorkerAbandon(pulse.abort_reason, ack=pulse.ack)
    if not remuxed:
        log(f"remux failed for {youtube_id}")
        report_fail(
            session, base_url, worker_name, job_id, remux_error[-2000:]
        )
        return

    log_hdr_metadata_outcome(config, youtube_id, encoded_path, out_path)

    log(f"uploading {youtube_id}")
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
        config["encode"]["quality"],
        config["encode"].get("preset"),
        encode_args,
        OUTPUT_CONTAINER,
    )


def handle_job(job: dict, session, base_url: str, config: dict) -> None:
    """
    a local encode failure is reported and returns normally - it is a
    completed job outcome, not an abandon.

    The heartbeat starts before the download, not at the encode:
    download plus probe can outlast the server's 60s stale-lease window
    on a large source, and the lease was getting reaped before the
    first heartbeat ever went out.
    """
    worker_name = config["worker"]["name"]
    heartbeat_interval = config["worker"]["heartbeat_interval"]
    temp_dir = config["worker"]["temp_dir"]
    job_id = job["id"]
    youtube_id = job["youtube_id"]
    target_height = job["target_height"]

    log(f"claimed {youtube_id} -> {target_height}p")

    src_path, encoded_path, out_path = _job_paths(
        temp_dir, youtube_id, target_height
    )

    progress_state = {"fraction": 0.0}
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
        download_source(session, base_url, job, src_path)
        if pulse.aborted:
            raise WorkerAbandon(pulse.abort_reason, ack=pulse.ack)

        source_hdr = probe_hdr_static_metadata(config, src_path)
        if source_hdr:
            log(f"{youtube_id}: source has {', '.join(sorted(source_hdr))}")
        if pulse.aborted:
            raise WorkerAbandon(pulse.abort_reason, ack=pulse.ack)

        cmd = build_handbrake_cmd(
            config, src_path, encoded_path, target_height
        )
        encode_args = shlex.join(cmd)
        log(f"encoding {youtube_id}: {encode_args}")

        proc, output_tail = spawn_handbrake(cmd, progress_state)
        while proc.poll() is None:
            if pulse.aborted:
                proc.kill()
                proc.wait(timeout=10)
                raise WorkerAbandon(pulse.abort_reason, ack=pulse.ack)
            time.sleep(0.5)

        if proc.returncode != 0:
            message = "".join(output_tail)[-2000:]
            log(f"encode failed ({proc.returncode}) for {youtube_id}")
            report_fail(session, base_url, worker_name, job_id, message)
            return

        deliver_result(
            job,
            session,
            base_url,
            config,
            encoded_path,
            out_path,
            encode_args,
            pulse,
            progress_state,
        )
    finally:
        pulse.stop()


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
    # own subdirectory per worker, so two workers sharing a configured
    # temp_dir never sweep or overwrite each other's files
    config["worker"]["temp_dir"] = os.path.join(
        config["worker"]["temp_dir"], config["worker"]["name"]
    )
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
            elif exc.fail_message:
                report_permanent_failure(
                    session,
                    base_url,
                    worker_name,
                    job["id"],
                    exc.fail_message,
                )
        except Exception as exc:  # pylint: disable=broad-except
            # a single job's failure must never kill the worker loop:
            # the server reaps the stale lease and requeues the job
            log(f"unexpected error on {youtube_id}, abandoning: {exc}")
        finally:
            cleanup_job_temp(temp_dir, youtube_id, job["target_height"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log("stopping")
