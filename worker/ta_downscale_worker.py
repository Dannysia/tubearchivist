#!/usr/bin/env python3
"""
TubeArchivist remote downscale worker.

Standalone sister app for a machine with a fast hardware encoder (e.g. an
RTX 5090 running NVENC on Windows). Polls TA's worker API for the oldest
queued downscale job, downloads the source, encodes it locally, uploads
the result, and reports completion. TA is the single source of truth for
the queue; this script keeps no state between loop iterations.

Encoding is delegated to HandBrakeCLI rather than driving ffmpeg
directly - HandBrake has solved HDR10 static metadata preservation
through an NVENC re-encode in production for years (automatic mastering-
display/content-light-level passthrough), which is meaningfully more
battle-tested than this script hand-rolling ffmpeg color-metadata flags
itself.

Each job therefore runs three tools: HandBrakeCLI encodes to MKV,
ffmpeg stream-copies that into the MP4 TA actually stores, and ffprobe
checks what HDR metadata survived. The MKV-then-MP4 detour exists
because HandBrake's NVENC metadata handling is documented for MKV while
TubeArchivist is MP4-only outside this feature - see ENCODE_CONTAINER
below, docs/downscale-hdr/README.md for the reasoning, and
docs/remote-downscale/windows-host-setup.md for how to verify it on
real hardware.

Third-party Python dependency: requests. External binaries this script
shells out to: HandBrakeCLI (encode), ffmpeg (remux), ffprobe (probe).
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

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB, source-download streaming reads

# "a couple of lease periods" (worker.md) - the server's own stale-lease
# threshold is 60s (STALE_LEASE_SECONDS in downscale/src/worker.py); a
# network call that keeps failing past this window is abandoned rather
# than retried forever, since the server will have reaped the lease
# anyway by the time this elapses.
NETWORK_RETRY_ABANDON_SECONDS = 120

# a stream copy runs at disk speed, so this is a "something is wedged"
# backstop rather than a real expectation - a 20 GB remux over a slow
# disk still lands well inside it
REMUX_TIMEOUT = 1800

# HandBrake encodes to MKV, then the result is remuxed to MP4 before
# upload. Both halves of that are deliberate:
#
# - MKV for the encode, because HandBrake writes HDR10 static metadata
#   only at the container level when using NVENC (not into the
#   bitstream), and MKV is the container that behavior is documented
#   for - see docs/downscale-hdr/README.md.
# - MP4 for what TA actually stores, because TA is MP4-only well beyond
#   this feature: the filesystem scanner only sees *.mp4 (and deletes
#   indexed videos it can't see), reindex rebuilds media_url with a
#   hardcoded .mp4, subtitle paths are derived by string-replacing
#   ".mp4", and metadata embedding goes through mutagen's MP4-specific
#   API. Handing TA an .mkv means silent, permanent media loss.
#
# The remux is a stream copy, not a re-encode - no quality cost, seconds
# of work. Whether it carries HandBrake's container-level HDR10 metadata
# across is the one thing that can't be settled without a real NVENC
# encode, so handle_job probes before and after and logs the answer.
ENCODE_CONTAINER = "mkv"
OUTPUT_CONTAINER = "mp4"


class WorkerAbandon(Exception):
    """
    raised to unwind out of the current job and move on to the next
    claim. Covers lease loss (409 conflict - "409 means abandon, never
    retry" in worker.md), an explicit stop request (ack=True: the worker
    owes the server a DELETE to acknowledge it), and a network outage
    that outlasts the bounded retry window.

    fail_message is set when the job can't succeed on a retry either -
    TA rejected the request itself rather than failing to receive it -
    and carries the reason to report so the job ends up failed instead
    of silently reaped and requeued.
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

    # HandBrake happily takes a fractional -q (22.5 is idiomatic for
    # x264/x265), but TA stores quality as an ES integer and its finish
    # endpoint rejects anything else. Caught here rather than left to
    # surface as a 400 after a job has already been downloaded and
    # encoded - which is both a long wait for a config typo and a job
    # that gets requeued and re-encoded on the same bad value.
    if isinstance(encode["quality"], bool) or not isinstance(
        encode["quality"], int
    ):
        raise SystemExit(
            "worker.toml: [encode] quality must be a whole number "
            f"(got {encode['quality']!r}) - TA records it as an integer"
        )

    return config


def build_session(config: dict) -> requests.Session:
    """DRF token auth, same as any other TA API client"""
    session = requests.Session()
    session.headers["Authorization"] = f"Token {config['server']['token']}"
    return session


# --------------------------------------------------------------------------
# WSL / Windows path handling


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
    convert a POSIX path to the Windows-style path ffprobe.exe/
    HandBrakeCLI.exe expect, when this script runs under WSL invoking
    Windows binaries directly - see worker.md "Windows/WSL specifics". A
    no-op under native Windows Python, where paths are already
    Windows-style.
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


def _ffprobe_path(config: dict) -> str:
    """
    ffprobe lives next to ffmpeg in the standard Windows builds, so its
    path is derived from ffmpeg_path unless overridden. Both binaries
    are genuinely used: ffmpeg for the MKV->MP4 remux, ffprobe for HDR
    metadata probing. Neither does any encoding - that's HandBrakeCLI.
    """
    return config["encode"].get("ffprobe_path") or _sibling_binary(
        config["encode"]["ffmpeg_path"], "ffprobe"
    )


# --------------------------------------------------------------------------
# source probing (ffprobe)


# side_data_type strings ffprobe reports for HDR10 static metadata -
# stable, human-readable labels (not a numeric enum) across ffprobe
# versions
HDR_STATIC_METADATA_SIDE_DATA_TYPES = {
    "Mastering display metadata",
    "Content light level metadata",
}


def probe_hdr_static_metadata(config: dict, path: str) -> set[str]:
    """
    the HDR10 static metadata types (mastering display colour volume,
    content light level) present on a file's first video stream, as a
    set - empty when there are none, or when the probe itself failed
    (an unreadable value isn't evidence of absence, but it isn't
    evidence of presence either, and this only drives logging).

    Checks stream *and* frame side data, because the two carry the
    metadata in different places and ffprobe reports them separately:

    - written into container elements (what HandBrake does for NVENC),
      ffprobe surfaces it as stream-level side data
    - written into the bitstream as SEI (what software encoders like
      x265 and SVT-AV1 do), it appears only as frame-level side data

    Checking -show_streams alone - which this did originally - silently
    misses every SEI-carried source, i.e. most HDR that wasn't produced
    by a hardware encoder. Verified both ways against real files; see
    docs/downscale-hdr/README.md.

    -read_intervals %+#1 limits frame parsing to the first frame, so
    this stays cheap on a multi-GB input.
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


# --------------------------------------------------------------------------
# remux (ffmpeg)


def build_remux_cmd(
    config: dict, encoded_path: str, out_path: str
) -> list[str]:
    """
    build the ffmpeg argv that rewraps HandBrake's MKV as MP4.

    -c copy makes this a stream copy: the encoded bitstream is written
    through untouched, so there is no second generation of quality loss
    and no GPU work - only the container changes.

    -map 0:v:0 -map 0:a? takes the video stream and any audio, and
    deliberately leaves subtitle streams behind: MKV accepts subtitle
    codecs MP4 has no place for, which would fail the copy outright. TA
    keeps subtitles as sidecar .vtt files rather than muxed-in streams,
    so there is nothing to lose here.

    +faststart moves the moov atom to the front, which is what lets TA's
    player start playback before the whole file has been fetched.
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
    """
    run the remux, returning (ok, error_output). A stream copy is fast
    but not instant on a multi-GB file, so callers keep a heartbeat
    running across it - long enough to lose a lease otherwise.
    """
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
    report whether the remux carried HDR10 static metadata across.

    This is the one part of the pipeline that couldn't be settled by
    reading documentation: HandBrake writes the metadata into the MKV
    container for NVENC, and whether ffmpeg reproduces it as MP4
    mdcv/clli boxes on a stream copy is a question about a specific
    ffmpeg build and a specific encoder. Rather than assume either way,
    probe both files and say what actually happened - so the answer
    shows up in the worker's own log on the first real HDR job instead
    of being discovered later as washed-out playback.
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


# --------------------------------------------------------------------------
# HandBrakeCLI


def build_handbrake_cmd(
    config: dict, src_path: str, out_path: str, target_height: int
) -> list[str]:
    """
    build the HandBrakeCLI argv. --non-anamorphic + only --height set is
    HandBrake's equivalent of ffmpeg's scale=-2:H - auto-computed width
    preserving aspect ratio, square pixels.

    NOT --keep-display-aspect: that flag only takes effect under
    --custom-anamorphic (see `HandBrakeCLI -h`) and is a silent no-op
    otherwise. Confirmed on real hardware 2026-08-14: --height 720
    --keep-display-aspect alone left storage width at the source's
    (3840 on a 4K source) and faked the display size via a 1:3 pixel
    aspect ratio instead of actually downscaling - every job encoded
    before this fix produced anamorphic output at ~3x the intended
    pixel count, not a real resize. --non-anamorphic forces 1:1 pixels,
    which is what makes an unset --width actually auto-compute a
    proportional value instead of defaulting to the source's.
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
# Not verified against a live run in this environment - if the actual
# installed version's wording differs, progress just stays at 0 (see
# _read_handbrake_output's docstring), it doesn't break the encode
# itself. Worth confirming against real output early on.
_HANDBRAKE_PROGRESS_RE = re.compile(r"task \d+ of \d+, (\d+(?:\.\d+)?)\s*%")


def _read_handbrake_output(
    proc: subprocess.Popen, progress_state: dict, tail: list[str]
) -> None:
    """
    background reader for HandBrakeCLI's combined stdout+stderr (merged
    via stderr=STDOUT in spawn_handbrake - HandBrakeCLI's exact split of
    progress vs. logging between the two streams isn't reliably
    documented enough to assume one over the other). Progress is capped
    at 0.99 - 1.0 is reserved for the upload/finish phase.

    Plain line iteration is enough even though CLI progress bars update
    in place with \\r rather than a newline per update: the pipe is
    opened in text mode, and universal-newlines translation turns a bare
    \\r into \\n before the iterator sees it, so each in-place repaint
    still arrives as its own line rather than one buffered blob at exit.
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
    start HandBrakeCLI and its output reader thread. progress_state is
    the same dict a LeaseHeartbeat already running for this job reads
    from (see handle_job) - the reader thread writes encode progress
    into it directly rather than owning a separate one.
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


# --------------------------------------------------------------------------
# TA API calls


def _permanent_http_status(exc: Exception) -> int | None:
    """
    the status code if exc is an HTTP error the server will keep
    returning for the same request, else None. 408 and 429 are the two
    4xx that explicitly mean "try again", so they stay retryable, as
    does every 5xx. 409 never reaches here - each caller checks for it
    before raise_for_status and raises WorkerAbandon itself.
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
    status plus whatever the server said about it - DRF puts the actual
    validation error in the body ({"quality": ["A valid integer is
    required."]}), which is the only thing that makes a rejection
    diagnosable from the TA side afterwards
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
    retry fn() with exponential backoff for up to
    NETWORK_RETRY_ABANDON_SECONDS on a network blip
    (requests.RequestException) before giving up with WorkerAbandon -
    "network blips != job failure" in worker.md. fn() raising anything
    else (WorkerAbandon for a 409, in particular) is not a network blip
    and passes straight through unretried.

    A 4xx other than 409 is the server rejecting the request itself, not
    a blip: retrying an identical payload can only produce an identical
    rejection, so it abandons immediately rather than burning the full
    retry window first.
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
    claim the oldest claimable job, or None if there's nothing to claim
    or the request itself failed - either way just means "try again next
    poll", no lease is held yet so there's nothing to abandon
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
        # subclasses, so an error status or a garbled body is caught
        # here too - claim runs outside main()'s per-job try/except, so
        # anything escaping it takes the whole worker process down
        # rather than costing one poll (worker.md, "a single job's
        # failure never crashes the worker loop")
        log(f"claim failed: {exc}")
        return None


def download_source(session, base_url, job, dest_path) -> None:
    """
    GET the source file. source_url is TA's plain nginx-served static
    path (/youtube/...), not a job-scoped API endpoint - Django's
    FileResponse over the ASGI/uvicorn worker pool was found to retain
    the full file size in that worker process's memory for as long as
    it ran, with no such growth when nginx serves the same bytes
    directly. No ownership check happens here as a result (the old
    job-scoped endpoint's 409-on-conflict is gone with it), but that
    was never a real access boundary - the same file is already
    reachable by any authenticated user through the normal download
    path regardless of job state. Auth is still required (nginx's
    auth_request), carried by the session's Authorization header same
    as every other call.
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
                # same rule as _call_with_backoff, which this path
                # doesn't share: a refused request won't start being
                # accepted, so don't spend the whole retry window on it.
                # No fail_message - this kills a partial encode with no
                # result to report, and a heartbeat being refused points
                # at a worker-wide problem (auth, config) rather than
                # anything wrong with this particular job, so letting it
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
    encode_args,
    container,
) -> None:
    """
    POST finish, reporting what was actually run. The server's field is
    still named ffmpeg_args (API contract, unchanged) even though this
    worker's argv is a HandBrakeCLI command now, not ffmpeg's - it's
    documented as a provenance record of the actual encode command, not
    specifically an ffmpeg one (ta-server.md).

    container is the bare extension of what was actually produced (mkv
    here). TA fixes a job's tmp_file_path to .mp4 when it's enqueued,
    long before it knows a remote worker will take it, so without this
    the server would keep calling the uploaded file .mp4 no matter what
    is really in it - see worker.md's "Output container".
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


def report_permanent_failure(
    session, base_url, worker_name, job_id, message
) -> None:
    """
    mark a job failed after TA rejected one of its requests outright.

    Without this the worker just stops touching the job, its lease goes
    stale, and the reaper requeues it - so the next claim re-downloads
    and re-encodes the same video into the same rejection, forever, at
    full GPU load. A request TA refuses (a bad quality type, a payload
    it won't validate) will be refused identically next time, so the
    honest end state is failed-with-a-reason, which also surfaces the
    server's own error text in the queue UI.

    Guarded rather than trusting: report_fail is best-effort and
    swallows its own WorkerAbandon already (logging that it gave up),
    but this runs from inside the main loop's exception handler, where
    anything that did escape would take the worker process down - the
    fail call gets rejected too when the original rejection was an auth
    error. Falling through to the reaper is the pre-existing behavior,
    so failing here is no worse than not trying.
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
    startup any leftover file from a previous crash is just discarded.

    temp_dir is expected to already be this worker's own subdirectory
    (see main() - it's temp_dir/<worker name>, not the raw config
    value), so this never touches another concurrently-running worker's
    files even when multiple workers share the same configured parent
    temp_dir. Per-file try/except is still worth it even so: a fresh
    restart of this same worker can race its own just-exited process for
    a file handle on Windows (see windows-host-setup.md §8) - log and
    move on rather than crash startup over a file that'll just get
    cleaned up next time.
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
    the (source, encoded, output) temp paths for a job - single source
    of truth, so handle_job and cleanup_job_temp can't disagree about
    what a job leaves lying around. Getting that wrong doesn't fail
    loudly, it just silently strands multi-GB files on every job.

    Three files, not two: HandBrake's MKV and the remuxed MP4 coexist
    on disk until cleanup, so temp_dir needs room for source + encode +
    remux at once.
    """
    src_path = os.path.join(temp_dir, f"{youtube_id}.src")
    base = os.path.join(temp_dir, f"{youtube_id}_{target_height}p.out")
    return src_path, f"{base}.{ENCODE_CONTAINER}", f"{base}.{OUTPUT_CONTAINER}"


def cleanup_job_temp(temp_dir: str, youtube_id: str, target_height: int):
    """
    Best-effort: a file HandBrake/ffmpeg still holds open raises
    PermissionError on Windows (see windows-host-setup.md §8). This runs
    from the main loop's `finally`, so letting that propagate would kill
    the whole worker over one leftover temp file - log and move on;
    sweep_temp_dir() picks up anything left behind on the next startup.
    """
    for path in _job_paths(temp_dir, youtube_id, target_height):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            log(f"cleanup failed for {path}, leaving for next sweep: {exc}")


# --------------------------------------------------------------------------
# one job


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
    everything after a successful encode: remux to MP4, upload, finish.

    Shares the single heartbeat pulse handle_job started right after
    claim, rather than starting a fresh one here - see handle_job's
    docstring for why that pulse now spans the whole job instead of
    just this tail end. progress_state is bumped to 1.0 (encoding
    itself only ever reports up to 0.99) since nothing after the encode
    has progress ticks of its own.
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
    run one claimed job through encode -> upload -> finish. Returns
    normally on success; raises WorkerAbandon on any cancel/conflict/
    network-exhaustion path. A local encode failure is reported via
    fail() and also returns normally - it's a completed job outcome, not
    an abandon.

    A single heartbeat pulse spans the whole job, started right here
    rather than only once encoding begins. download_source() and
    probe_hdr_static_metadata() together can take longer than the
    server's 60s stale-lease window on a large source or a slow link -
    with no heartbeat running yet during that stretch, the lease was
    getting reaped before this worker ever sent its first one, so the
    first heartbeat (once encoding did start) came back a 409 and
    abandoned a job that had barely begun. See STALE_LEASE_SECONDS in
    downscale/src/worker.py.
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
    # Own subdirectory per worker name, so two workers sharing the same
    # configured temp_dir never sweep or overwrite each other's files -
    # discovered 2026-08-14 running two workers concurrently: a restart
    # of one crashed trying to sweep a file the other had open
    # mid-encode (see sweep_temp_dir's docstring).
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
