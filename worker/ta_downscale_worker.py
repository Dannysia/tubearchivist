#!/usr/bin/env python3
"""TubeArchivist remote downscale worker. Third-party dependency: requests"""

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

NETWORK_RETRY_ABANDON_SECONDS = 120

REMUX_TIMEOUT = 1800

# HandBrake writes HDR10 static metadata under NVENC only at container
# level, which MKV carries. TA only indexes .mp4, so the result is
# remuxed by stream copy
ENCODE_CONTAINER = "mkv"
OUTPUT_CONTAINER = "mp4"


class WorkerAbandon(Exception):
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
    pass


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

    # TA stores quality as an integer
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
    if not _IS_WSL:
        return path
    result = subprocess.run(
        ["wslpath", "-w", path], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _sibling_binary(ffmpeg_path: str, name: str) -> str:
    """splits on the last "/" or "\\", ffmpeg_path may be a windows path"""
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
    """whether a stream copy keeps the mdcv/clli boxes depends on the build"""
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
    response = getattr(exc, "response", None)
    if response is None:
        return None

    status = response.status_code
    if 400 <= status < 500 and status not in (408, 429):
        return status

    return None


def _http_error_detail(exc: Exception, status: int) -> str:
    response = getattr(exc, "response", None)
    body = ""
    if response is not None:
        try:
            body = " ".join(response.text.split())[:500]
        except (ValueError, UnicodeError):
            body = ""

    return f"HTTP {status}: {body}" if body else f"HTTP {status}"


def _call_with_backoff(fn, description: str):
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
    """None means nothing to claim or the request failed"""
    url = urljoin(base_url, "/api/downscale/worker/claim/")
    body = {"worker": worker_name, "encoders": encoders}
    try:
        resp = session.post(url, json=body, timeout=(10, 30))
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log(f"claim failed: {exc}")
        return None


def download_source(session, base_url, job, dest_path) -> None:
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

    def raise_if_aborted(self) -> None:
        if self.aborted:
            raise WorkerAbandon(self.abort_reason, ack=self.ack)

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
) -> None:
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
            },
            timeout=(10, 30),
        )
        if resp.status_code == 409:
            raise WorkerAbandon("conflict")
        resp.raise_for_status()

    _call_with_backoff(_attempt, f"finish for job {job_id}")


def report_fail(session, base_url, worker_name, job_id, message) -> None:
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
    log(f"marking job {job_id} failed: {message}")
    try:
        report_fail(session, base_url, worker_name, job_id, message)
    except Exception as exc:  # pylint: disable=broad-except
        log(
            f"could not mark job {job_id} failed ({exc}) - "
            "leaving it for the server's reaper"
        )


def try_delete(session, base_url, worker_name, job_id) -> None:
    url = urljoin(base_url, f"/api/downscale/worker/jobs/{job_id}/")
    try:
        session.delete(
            url, headers={"X-TA-Worker": worker_name}, timeout=(10, 30)
        )
    except requests.RequestException as exc:
        log(f"could not delete/ack job {job_id}: {exc}")


def sweep_temp_dir(temp_dir: str) -> None:
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
    src_path = os.path.join(temp_dir, f"{youtube_id}.src")
    base = os.path.join(temp_dir, f"{youtube_id}_{target_height}p.out")
    return src_path, f"{base}.{ENCODE_CONTAINER}", f"{base}.{OUTPUT_CONTAINER}"


def cleanup_job_temp(temp_dir: str, youtube_id: str, target_height: int):
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
    worker_name = config["worker"]["name"]
    job_id = job["id"]
    youtube_id = job["youtube_id"]

    log(f"encoded {youtube_id}, remuxing to {OUTPUT_CONTAINER}")
    progress_state["fraction"] = 1.0

    remuxed, remux_error = run_remux(config, encoded_path, out_path)
    pulse.raise_if_aborted()
    if not remuxed:
        log(f"remux failed for {youtube_id}")
        report_fail(
            session, base_url, worker_name, job_id, remux_error[-2000:]
        )
        return

    log_hdr_metadata_outcome(config, youtube_id, encoded_path, out_path)

    log(f"uploading {youtube_id}")
    upload_result(session, base_url, worker_name, job_id, out_path, pulse)
    pulse.raise_if_aborted()

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
    )


def handle_job(job: dict, session, base_url: str, config: dict) -> None:
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
        pulse.raise_if_aborted()

        source_hdr = probe_hdr_static_metadata(config, src_path)
        if source_hdr:
            log(f"{youtube_id}: source has {', '.join(sorted(source_hdr))}")
        pulse.raise_if_aborted()

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
                pulse.raise_if_aborted()
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
            log(f"unexpected error on {youtube_id}, abandoning: {exc}")
        finally:
            cleanup_job_temp(temp_dir, youtube_id, job["target_height"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log("stopping")
