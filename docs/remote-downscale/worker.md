# Remote downscale — worker (sister app)

Status: **implemented** (`worker/ta_downscale_worker.py`), **never run
on real hardware**. The script is complete and its pure logic has been
exercised piece by piece, but no job has been encoded on the 5090 and
`worker/` has no automated test suite. Anything here describing
HandBrake's actual behaviour — preset/tune names, the `-q` scale, the
progress output it prints — came from documentation, not observation.
[windows-host-setup.md](windows-host-setup.md) is the runbook for
confirming it, and §10 there lists what remains unverified.

See [README.md](README.md) for the overall architecture and
[ta-server.md](ta-server.md) for the API this client consumes.

The first (and for now only) deployment target: a Windows gaming PC with an
RTX 5090, using its NVENC AV1 hardware encoder.

## Shape

A **single-file Python script** (`worker/ta_downscale_worker.py` in this
repo), Python 3.11+. Third-party Python dependency: `requests`. It shares
no code with the TA backend — the API contract is the only coupling — so
it can be copied to the PC as one file plus one config file.

Three external binaries this script shells out to, beyond that one
Python dependency:

- **`HandBrakeCLI`** does the actual encode, to `.mkv`. See "Why
  HandBrake, not raw ffmpeg" below and
  [downscale-hdr/README.md](../downscale-hdr/README.md) for the full
  reasoning — in short, HandBrake has solved HDR10 static metadata
  preservation through an NVENC re-encode in production for years, which
  is meaningfully more battle-tested than this script hand-rolling
  ffmpeg color-metadata flags itself.
- **`ffmpeg`** stream-copies that MKV into the `.mp4` TA actually
  stores. No re-encode — see "Output container" below.
- **`ffprobe`** reads HDR metadata off the source and the remuxed
  result, to confirm nothing was dropped in between.

First run on a real machine: follow
[windows-host-setup.md](windows-host-setup.md).

No daemon framework, no packaging. Later it can be wrapped in a Windows
service (NSSM) or Task Scheduler job; the script itself is just a loop.

## Why HandBrake, not raw ffmpeg

The original design drove ffmpeg directly. That changed once HDR
preservation became a stated goal: HandBrake automatically passes through
mastering-display and content-light-level metadata from source to output
with zero flag-wrangling, which raw ffmpeg does not do reliably (see
downscale-hdr/README.md's "Battle-tested prior art" section for the full
comparison, including why `pymediainfo` was considered and rejected for
this worker specifically).

One real caveat carries over regardless of encode backend: HandBrake's
own docs state HDR10 metadata is written **only in the container, not the
bitstream, when using NVIDIA NVEnc**. That's why the worker *encodes* to
`.mkv` — the container that behavior is documented for — and then
rewraps to the `.mp4` TA can actually store. See "Output container"
below for why both halves are forced.

## The NVENC / WSL2 gotcha

NVENC is **not available inside WSL2**: NVIDIA's WSL driver exposes CUDA
but not the video encode engine (`libnvidia-encode` isn't provided), and
Docker Desktop's GPU support inherits the same limitation. Linux ffmpeg or
HandBrakeCLI in WSL therefore cannot use the 5090's encoder.

The clean way out: **WSL can execute Windows binaries directly**. The
worker script can run inside WSL for comfort and invoke `HandBrakeCLI.exe`,
`ffmpeg.exe`, and `ffprobe.exe` (native Windows builds), and those
processes run natively with full GPU access. Requirements when doing so:

- temp/working files live on a Windows-visible path (e.g. `/mnt/c/ta-work`)
- paths passed to any of the three binaries are converted with `wslpath -w`

Running the whole script under native Windows Python is equally fine and
removes the path translation. Config makes this a choice, not a fork:
`handbrake_path`/`ffmpeg_path` can point at the `.exe` either way.

## Output container: encode MKV, deliver MP4

The worker encodes to `.mkv` and then **stream-copies that into `.mp4`**
before uploading. Both halves are forced, from opposite directions.

**MKV for the encode**, because of the NVENC caveat above: HandBrake
writes HDR10 metadata only into the container, so the container it lands
in is load-bearing, and MKV is the one that behavior is documented for.

**MP4 for what TA stores**, because TubeArchivist is MP4-only well
beyond this feature, and handing it an `.mkv` means silent, permanent
media loss:

- `appsettings/src/filesystem.py` builds its "what's on disk" set from
  `*.mp4` only. An accepted `.mkv` is indexed but invisible to the
  scanner, so `Scanner.delete()` treats it as an orphaned index entry
  and **deletes the file, the ES doc, its comments, subtitles, and
  playlist entries**.
- `video/src/index.py`'s `add_file_path()` rebuilds `media_url` with a
  hardcoded `.mp4` on every reindex — and `check_reindex` is
  auto-scheduled at startup with a 90-day window, so this needs no user
  action to fire.
- `video/src/subtitle.py` derives sidecar paths by string-replacing
  `".mp4"`, and `video/src/meta_embed.py` embeds metadata through
  mutagen's MP4-specific API.

An earlier revision of this design shipped `.mkv` all the way to TA. It
never worked: `MediaStreamExtractor` discards video streams with no
`bit_rate`, Matroska has no per-track bitrate field, so `_get_height()`
returned `None` for every `.mkv` and the server rejected every upload as
invalid output — after a full download, encode, and upload. The three
paths above would then have deleted the results had it gotten that far.

The remux is `ffmpeg -c copy` (see `build_remux_cmd()`): a rewrap, not a
re-encode, so no second generation of loss and no GPU time. It also
applies `+faststart`, which the MKV path couldn't offer at all, so
accepted results stream properly in TA's own player.

`log_hdr_metadata_outcome()` probes before and after and logs whether
the metadata survived — see
[windows-host-setup.md](windows-host-setup.md) §6, which is where that
question actually gets settled.

The `container` field on finish still reports what was produced (`mp4`),
and `DownscaleReview.accept()` still matches the candidate's real
extension — see [ta-server.md](ta-server.md). Both now agree with TA's
enqueue-time assumption rather than fighting it, so they're a guard
against future drift rather than load-bearing machinery. Local encodes
are unaffected: still `.mp4` via raw ffmpeg, unchanged.

## Configuration

`worker.toml` next to the script:

```toml
[server]
url = "http://tubearchivist.local:8000"
token = "…"                 # TA API token (Settings → API)

[worker]
name = "gaming-pc"          # unique per worker; used for job ownership
temp_dir = "/mnt/c/ta-work" # or C:\ta-work under native Windows
poll_interval = 30          # seconds between claim attempts when idle
heartbeat_interval = 10     # must be well under the server's 60s lease

[encode]
ffmpeg_path = "ffmpeg.exe"      # only used to derive ffprobe's path
handbrake_path = "HandBrakeCLI.exe"
encoder = "nvenc_av1"            # HandBrake's naming (prefixed), not
                                  # ffmpeg's (av1_nvenc, suffixed)
preset = "slow"                  # HandBrake's own preset vocabulary
# tune = "hq"
quality = 24                     # HandBrake's -q/--quality; whole
                                  # numbers only (TA stores an integer)
extra_args = []
```

`quality` is validated at startup rather than trusted: HandBrake accepts
a fractional `-q`, TA's `quality` field is an ES `integer`, and the
mismatch would otherwise only surface as a rejected `finish` after a
full download-and-encode — then get requeued and re-encoded on the same
bad value. The worker refuses to start instead.

The worker deliberately owns its encoder settings (see README); the
configured `quality` always wins. TA's `quality_hint` from the claim
response is ignored outright — the script doesn't read it (nor `title`),
it just isn't a meaningful input when the scales differ this much
between encoders. If a mapping from TA's CRF-ish hint ever seems
desirable it can be added later; an explicit local setting is more
honest in the meantime.

**Not verified against a live HandBrakeCLI install** while writing this
(no real GPU/binary available in the environment this was scoped from):
the exact `preset`/`tune`/`quality` values above. Confirm with
`HandBrakeCLI --encoder-list`, `--encoder-preset-list=nvenc_av1`, and
`--encoder-tune-list=nvenc_av1` on the actual machine before trusting
them — HandBrake 1.10 specifically refined the NVENC constant-quality
range, so older guides' quality numbers may not carry over cleanly.

## The encode command

`build_handbrake_cmd()` in the worker script:

```
HandBrakeCLI.exe
  -i <src> -o <out>.mkv
  -e nvenc_av1
  -q 24
  --height <target_height> --non-anamorphic
  --encoder-preset slow
  [--encoder-tune <tune>]
  [extra_args...]
```

`--height` + `--non-anamorphic` is HandBrake's equivalent of ffmpeg's
`scale=-2:H` — auto-computed width preserving aspect ratio, square
pixels. **Not** `--keep-display-aspect`: that flag only takes effect
under `--custom-anamorphic` and is a silent no-op otherwise — confirmed
on real hardware, every job encoded before this was caught came out
anamorphic (storage width left at the source's, aspect faked via a
non-1:1 pixel aspect ratio instead of a real resize). See
[windows-host-setup.md](windows-host-setup.md) §3/§11 for the full
story. HDR10 static metadata, color primaries/transfer/matrix all get
carried through automatically by HandBrake itself; nothing in this
command needs to ask for that explicitly.

The exact argv is captured (`shlex.join`) and reported in the finish
call — it becomes the job's/video's permanent `ffmpeg_args` record (the
server-side field name predates this worker using HandBrake instead of
ffmpeg directly; it's documented as a provenance record of the actual
encode command, not specifically an ffmpeg one, so the field wasn't
renamed).

## Main loop

```
loop:
  job = POST /claim (204 → sleep poll_interval, retry)
  GET source → temp_dir/<youtube_id>.src (stream to disk)
  spawn HandBrakeCLI, parse its console progress line for percent complete
  every heartbeat_interval:
      POST heartbeat {progress}
      → {"stop": true}?  kill it, DELETE job, clean temp, continue
      → 409?             abandon: kill it, clean temp, continue
  exit != 0 → POST fail {output tail}, clean temp, continue

  start heartbeat thread (same cadence, progress=1.0), keep it running
  through all three of the following:
    ffmpeg -c copy  <out>.mkv -> <out>.mp4   (rewrap, no re-encode)
      → non-zero? POST fail {ffmpeg stderr}, clean temp, continue
      → probe both, log whether HDR10 static metadata survived
    PUT result (stream upload)
    POST finish {encoder, quality, preset, ffmpeg_args, container}
  stop heartbeat thread
  → any heartbeat during this window returns {"stop": true} or 409?
    abort the upload/finish call in flight, clean temp, continue
  → PUT or POST finish itself returns 409? abandon: clean temp, continue
  → any other 4xx (not 408/429)? POST fail {server's error},
    clean temp, continue - retrying can't change the answer

  clean temp, loop immediately
```

Rules that make this robust:

- **One job at a time.** The 5090 could run several NVENC sessions, but one
  keeps the worker trivial; parallelism is a later option (multiple claims,
  one thread each).
- **Heartbeat never stops just because the encode exited.** The
  remux/upload/finish phase can run long for a large source (a stream
  copy is quick but not free, and no LAN is instant for multi-GB
  transfers) with no natural progress ticks of its own -
  keeping the heartbeat alive through that phase (progress pinned at 1.0)
  is what keeps the server-side lease fresh and lets a cancel actually
  land before the job reaches `pending_review`. Skipping this reintroduces
  the exact race the server's lease/reap design exists to avoid: without a
  live heartbeat, a slow upload can outlast the server's stale-lease
  threshold and get reaped-and-reclaimed while still in flight.
- **409 means abandon, never retry.** Any job-scoped call returning 409
  says the server reaped/requeued/cancelled the job — stop touching it,
  clean local temp, go back to claiming. This is the entire conflict-
  resolution story; the worker never argues with the server.
- **Network blips ≠ job failure.** Heartbeat/upload failures retry with
  backoff for a bounded window (a couple of lease periods). If TA stays
  unreachable longer than that, the server has reaped the job anyway —
  abandon and start over. The encode is never aborted just because one
  heartbeat failed.
- **A rejected request isn't a blip, and isn't retried by requeueing
  either.** A 4xx other than 409 (and other than 408/429, which
  explicitly mean "try again") means the server refused the request
  itself — an unchanged payload will be refused identically next time.
  So the worker stops immediately rather than spending the full retry
  window, *and* reports the job failed with the server's own error text
  instead of just walking away. Walking away would leave the lease to go
  stale, the reaper to requeue it, and the next claim to re-download and
  re-encode the same video into the same rejection — a silent loop at
  full GPU load, which is the worst possible outcome for an unattended
  library run. Failed-with-a-reason is visible in the queue UI and
  stops.

  Two deliberate exceptions. A **network** failure still requeues: TA
  being unreachable says nothing about whether the job can succeed, and
  a retry is exactly right once it's back. A **heartbeat** rejection
  also requeues rather than failing the job — it kills a partial encode
  that has no result to report, and a refused heartbeat points at a
  worker-wide problem (auth, config) rather than anything wrong with
  that particular video.
- **Crash-safe by construction.** All state lives on the server; the worker
  keeps nothing between iterations. On startup it sweeps `temp_dir` of
  leftovers from a previous crash. A worker crash mid-job is simply a
  stale lease the server reaps.
- **Progress comes directly from HandBrakeCLI's own percentage output** -
  a regex against its console progress line
  (`task N of M, XX.XX %`), not a duration-based calculation the way the
  old ffmpeg-driven design worked. A background thread iterating the
  merged stdout/stderr pipe line by line is enough, even though CLI
  progress bars repaint in place with `\r` instead of emitting a line
  per update: the pipe is opened in text mode, and universal-newlines
  translation converts a bare `\r` to `\n` before the iterator sees it,
  so each repaint arrives as its own line as it happens rather than one
  buffered blob at exit (verified against a CR-updating stand-in
  process). **Not
  verified against a live HandBrakeCLI's actual output** - if the real
  wording differs, progress just silently stays near 0 rather than
  breaking the encode (see `_read_handbrake_output`'s docstring), but it's
  worth confirming against a real run early on.

Implementation notes (where the shipped script makes a concrete choice the
pseudocode above leaves open):

- **`PUT result` is a plain, non-chunked upload**, not a raw generator
  stream. A WSGI server can't be assumed to support chunked request
  bodies, so the script wraps the output file in a small file-like object
  that reports its size via `__len__` (giving `requests` a real
  `Content-Length`) while still checking the concurrent heartbeat on every
  `read()` call — a cancel or lease loss detected mid-upload still aborts
  the transfer in flight, just via per-chunk-read polling rather than a
  chunked-encoding cutoff. The server's own ownership re-check before
  rename (see ta-server.md) remains the actual correctness backstop
  either way; this is a responsiveness optimization, not something
  correctness depends on.
- **Network blips get bounded retry on every call that touches the
  server**, not only heartbeats — claim, source download, upload, finish,
  and fail all retry with exponential backoff for up to
  `NETWORK_RETRY_ABANDON_SECONDS` (120s, "a couple of lease periods")
  before giving up and abandoning the job. `claim()` itself is the
  exception: a failed claim just means "nothing this round," so it logs
  and falls through to the next poll rather than retrying inline.
- **`ffprobe_path` defaults to `ffmpeg_path` with the binary name
  swapped** (`ffmpeg.exe` → `ffprobe.exe`, same directory) rather than
  requiring a second config value — matches how the gyan.dev/BtbN Windows
  builds ship both binaries side by side. Overridable via
  `encode.ffprobe_path` in `worker.toml` if that assumption doesn't hold
  for a given install.
- **A single job's failure never crashes the worker loop.** The main
  loop's per-job handling catches `WorkerAbandon` (the expected
  cancel/conflict/network-exhaustion cases) and, as a last resort, any
  other exception too — logged and treated as an abandon, so one bad job
  can't take the whole process down. Consistent with "crash-safe by
  construction": the server reaps the stale lease either way.

## Windows/WSL specifics

- Under WSL, every path handed to `ffprobe.exe`/`HandBrakeCLI.exe` goes
  through `wslpath -w`; the script otherwise works in POSIX paths.
- `temp_dir` sizing: needs room for **three** files at once — the
  source, HandBrake's MKV, and the remuxed MP4 all coexist until the job
  finishes. Budget roughly 3× the largest source, on an NVMe.
- Autostart later: Task Scheduler "at logon" running either
  `pythonw.exe worker.py` (native) or `wsl.exe -e python3 worker.py`
  (WSL). Not part of v1 — v1 is "run it in a terminal when the PC is on".
- Console output is the UI: one line per state change
  (claimed/encoding x%/uploading/done/abandoned), since there's no other
  observability on the Windows side. The TA queue UI shows the same
  progress via heartbeats.

## Explicit non-features (v1)

- No local queue or job persistence on the worker.
- No TLS/cert handling — LAN HTTP with token auth, matching the server
  scope.
- No self-update, no multi-encoder negotiation: the claim call sends the
  configured encoder name for logging only.
