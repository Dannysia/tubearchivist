# Downscale HDR detection and preservation

Status: **superseded on the worker, still draft for local.** The worker
no longer drives ffmpeg directly for encoding — it now shells out to
HandBrakeCLI (see [worker.md](../remote-downscale/worker.md#why-handbrake-not-raw-ffmpeg)),
which handles HDR10 static metadata passthrough automatically. The
fail-fast NVENC guard this doc originally scoped is gone: `_is_nvenc()`
was deleted once nothing gated on it, and `probe_has_hdr_static_metadata()`
became `probe_hdr_static_metadata()`, which returns the *set* of
metadata types found and is used to report what survived the MKV→MP4
remux rather than to refuse jobs. It also now checks frame side data as
well as stream side data — the original only checked the latter, which
silently missed every source carrying its metadata as SEI rather than
in container elements (most HDR not produced by a hardware encoder).
Everything below
about explicit color-tag passthrough / forced 10-bit / the VAAPI
`p010le` branch remains relevant only to the **local** ffmpeg-based
encoder, which is unchanged and out of scope for now (explicit user
decision - the local path "currently serves my needs").

## Motivation

Neither downscale path — the local celery runner
(`backend/downscale/src/downscale.py`) nor the remote worker
(`worker/ta_downscale_worker.py`) — looks at color metadata at all today.
Both re-encode (never stream-copy) without ever inspecting or explicitly
setting `color_primaries`/`color_transfer`/`color_space`, and neither
touches HDR10 static metadata (mastering display / max content light
level).

This isn't hypothetical: TA pulls from YouTube, which does host genuine
HDR uploads. An HDR source that loses or mismatches its color tags during
re-encode doesn't fail to decode — it plays back looking washed out or
badly contrasty, because the output still contains PQ/HLG-curve pixel
values but gets tagged (or defaults to) SDR, so players apply the wrong
EOTF. That's a silent quality regression a user could easily not notice
until they're actually watching the result.

Two separate concerns get conflated if you're not careful, and this doc
keeps them apart throughout:

- **Bit depth** (`pix_fmt`, e.g. `p010le` vs `nv12`/`yuv420p`) — how many
  bits per sample. A video can be 10-bit SDR with no HDR involved at all.
- **HDR-ness** — determined by the transfer characteristic (`smpte2084`
  aka PQ, or `arib-std-b67` aka HLG) and wide-gamut primaries
  (`bt2020`). Wide-gamut primaries alone don't make something HDR (some
  SDR masters use bt2020 primaries with an ordinary gamma curve); the
  transfer characteristic is the real signal.

## Detection

A dedicated probe, not a shared one. `MediaStreamExtractor`
(`backend/video/src/media_streams.py`) already runs
`ffprobe -show_streams -show_format` once per job (via `_get_height()`,
called from both `run()` locally and `_try_claim_candidate()` on the
worker side) — but it discards everything except
bitrate/codec/height/width/index/type, and its output is persisted
verbatim into `ta_video`'s `streams` field via `add_streams()`
(`backend/video/src/index.py:307-313`). Extending its shared shape would
leak new fields into the video index and frontend types for a
downscale-only concern, well beyond what this needs.

Instead: a small, purpose-built probe living in the downscale code on
each side, mirroring how the worker keeps its own dedicated probe
helpers rather than reusing anything shared (worker.md's own stated
principle — the worker shares zero code with the backend, only the API
contract).

**Local** (`downscale.py`), a new function alongside `_get_height`:

```python
HDR_TRANSFER_CHARACTERISTICS = {"smpte2084", "arib-std-b67"}


def probe_color_info(media_path: str) -> dict | None:
    """
    color_primaries/color_transfer/color_space for the first video
    stream, or None if ffprobe fails or the source has no tagged color
    metadata (common for older/simpler sources - absence means "assume
    SDR", not an error)
    """
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_primaries,color_transfer,color_space",
        "-of", "json", media_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    streams = json.loads(result.stdout).get("streams")
    return streams[0] if streams else None


def is_hdr(color_info: dict | None) -> bool:
    if not color_info:
        return False
    return color_info.get("color_transfer") in HDR_TRANSFER_CHARACTERISTICS
```

Called once in `run()` right next to the existing `_get_height()` call
(same lifecycle point, same original file), result threaded through to
`_encode()` → `_build_ffmpeg_cmd()`.

**Worker** (`ta_downscale_worker.py`): **no longer applicable.** This
originally proposed folding colour detection into the worker's
`probe_duration()` call and threading the result into its ffmpeg argv.
Neither exists any more — the worker drives HandBrakeCLI, which carries
colour primaries, transfer characteristics, and matrix through by
itself, so there is no argv to add tags to. `probe_duration()` was
deleted along with the rest of the ffmpeg progress machinery when the
encode backend changed.

What the worker does instead is *verify* rather than *instruct*:
`probe_hdr_static_metadata()` checks the encode and the remuxed result
and logs whether the metadata survived (see the guard section above).
Everything below in this doc is therefore **local-path only**.

## Superseded: the fail-fast guard became per-job reporting

The original plan here (below, kept for the record) was: the worker
refuses a job outright when it's about to lose real HDR10 static
metadata, instead of silently downscaling it away. That was the right
call *when the worker drove ffmpeg directly*, since raw ffmpeg + NVENC
genuinely does silently drop this metadata. It stopped being the right
call once the worker switched to HandBrakeCLI as its encode backend
(see worker.md) - HandBrake preserves this metadata automatically
(container-level, for NVENC specifically), so refusing those jobs would
be blocking work HandBrake can actually handle correctly.

Refusal was replaced by **measurement**, which is strictly more useful:
the worker probes the encode and the remuxed result and logs whether the
metadata actually survived, per job. That turns the open question into an
observation on real files rather than a prediction from documentation -
and unlike the guard, it covers the failure mode that can still bite
(the MKV→MP4 rewrap dropping container-level metadata), not just the one
HandBrake already solved. See
[windows-host-setup.md](../remote-downscale/windows-host-setup.md) §6.

What survives is `probe_hdr_static_metadata(config, path)` in
`ta_downscale_worker.py`, which returns the set of metadata types found
rather than a bool, and is called on the source (informational), then on
the encode and the remux to report whether the rewrap preserved them.
`_is_nvenc()` was deleted outright once nothing gated on the answer.

It runs an unrestricted `ffprobe -show_streams -show_frames
-read_intervals %+#1 -select_streams v:0 -of json <path>` (not the
narrower `-show_entries` form used elsewhere in this doc — side data
only shows up in the full JSON), and looks for a `side_data_type` of
`"Mastering display metadata"` or `"Content light level metadata"` in
**both** the stream and frame side-data lists.

Checking both matters and the original got it wrong: container-written
metadata (HandBrake's NVENC behavior) appears as *stream* side data,
while SEI-written metadata (x265, SVT-AV1 — most HDR that didn't come
off a hardware encoder) appears only as *frame* side data. The original
checked `-show_streams` alone and returned `False` for every
SEI-carried source. Verified against real files in both shapes.
`-read_intervals %+#1` parses only the first frame, so it stays cheap on
a multi-GB input. A probe failure still returns empty rather than
raising.

This only ever covered the worker's NVENC path. The local backend has no
NVENC path to guard in the first place, and this was never extended to
VAAPI even though VAAPI's raw-ffmpeg re-encode has the identical
metadata-loss problem the original guard was built for - out of scope
here since only the worker's NVENC path changed encode backend.

## Battle-tested prior art vs. hand-rolling flags

Before scoping the actual flags, it's worth checking whether something
more proven than guessing at ffmpeg options exists.

**Detection: `pymediainfo` (MediaInfo) considered, not adopted.**
MediaInfo is the real industry-standard tool here — instead of inferring
HDR-ness from a raw `color_transfer` string match (this doc's approach)
or matching ffprobe's internal `side_data_type` label strings (the
implemented fail-fast guard's approach), it exposes a direct, structured
`HDR_Format` field (`"HDR10"`, `"HDR10+"`, `"Dolby Vision"`, `"HLG"`) and
clean mastering-display/MaxCLL/MaxFALL values. `pymediainfo` (current on
PyPI, actively released - 7.0.1 as of writing) is a real, usable Python
binding. The catch: it's not pure Python, it binds to the native
`libmediainfo` shared library, so using it would mean a Dockerfile change
for the backend (installing `libmediainfo0v5` or similar) and, worse, a
native-library install on every worker's Windows machine — directly
against `worker.md`'s explicit design goal of a single-file script with
one dependency (`requests`). Since `ffprobe` is already a hard dependency
on the worker (needed for the encode itself) and the local backend has no
NVENC path to protect in the first place, **detection stays
ffprobe-based on both sides** - the accuracy gain from MediaInfo doesn't
justify a native dependency neither side currently needs for anything
else.

**Encode-side passthrough: HandBrake adopted as the worker's encode
backend, superseding the plan below for the worker specifically.** This
doc originally recommended treating HandBrake as reference-only prior
art (its HDR handling is embedded in a large C codebase, not an
importable library, and swapping the encode backend is a real
architecture change - different CLI surface, different filter/quality
model, a new dependency on the worker machine). That recommendation was
revisited and explicitly overridden: the worker's primary purpose is
using the 5090's hardware encoder on a large library, and getting HDR10
preservation right reliably matters more here than staying minimal on
tooling. Verified against HandBrake's actual current documentation
(not just general knowledge) before committing to this:

- HandBrake automatically passes through mastering-display and
  content-light-level metadata from source to output with zero
  configuration needed - confirmed directly, not assumed.
- **The real catch**: HandBrake's own docs state HDR10 metadata is
  written *only in the container, not the bitstream*, when using NVIDIA
  NVEnc (or AMD VCN). Since NVENC is the whole point of this worker,
  this applies. Container-level metadata is a real, commonly-relied-on
  pattern (most HDR content works this way), but it does make container
  choice load-bearing - see below.
- This is why the worker **encodes** to `.mkv` - MKV is the container
  this kind of metadata is reliably read from. It does not *deliver*
  `.mkv`, though: it stream-copies the result into `.mp4` before
  uploading.

  Delivering MKV was tried and was wrong. TubeArchivist is MP4-only far
  beyond this feature - the filesystem scanner enumerates `*.mp4` and
  deletes indexed videos it can't see, reindex rebuilds `media_url`
  with a hardcoded `.mp4` on an auto-scheduled 90-day cycle, subtitle
  paths are derived by replacing `".mp4"`, and metadata embedding uses
  mutagen's MP4-specific API. It also never actually ran: ffprobe
  reports no `bit_rate` for Matroska video streams, `MediaStreamExtractor`
  treats a missing `bit_rate` as "probably thumbnail" and drops the
  stream, so `_get_height()` returned `None` for every `.mkv` and the
  server rejected all of them as invalid output.

  The remux (`ffmpeg -c copy`) resolves both: HandBrake still writes
  into the container it's documented for, and TA still gets the only
  container it supports. Whether the rewrap carries container-level
  metadata across is verified per-job and logged - see
  [windows-host-setup.md](../remote-downscale/windows-host-setup.md) §6.
  Bitstream-carried (SEI) metadata is confirmed to survive it intact.

Local encoding is explicitly unaffected by any of this - it still runs
raw ffmpeg exactly as before, and the flag-level plan below remains the
relevant one *for local only*, should HDR passthrough ever get scoped
there too.

## What gets added to the ffmpeg command (local path only)

The worker no longer applies any of this - HandBrakeCLI handles color
tags and HDR passthrough on its own. Everything below only still applies
to the **local** ffmpeg-based encoder (`backend/downscale/src/
downscale.py`), which remains unchanged and out of scope for now.

**Explicit color tags, always, when detected** — on both paths, for any
encoder, whether or not the source is HDR:

```
-color_primaries <value> -color_trc <value> -colorspace <value>
```

This isn't purely an HDR concern — it's making explicit what today relies
on implicit frame-tag pass-through, which is a real gap for the worker's
`scale_cuda` path specifically (NPP/CUDA-family filters have a
version-dependent history of not reliably carrying primaries/transfer/
matrix tags through the way software `scale` generally does), and NVENC
via ffmpeg has also historically needed explicit flags to get color tags
written into the encoded bitstream's VUI/SPS headers rather than just
attached to raw frames.

**Force 10-bit output for HDR sources specifically**, overriding whatever
`pix_fmt` is configured:

- Encoding actual PQ/HLG pixel data in 8-bit crushes the curve and
  produces visible banding — this isn't a quality preference, it's
  close to always wrong. HDR detection should force `p010le` (or
  encoder-appropriate 10-bit equivalent) regardless of the worker's
  general `pix_fmt` setting.
- Locally, this also means the VAAPI hardware path's hardcoded
  `format=nv12,hwupload` (`downscale.py:237`) needs an HDR-aware branch —
  `nv12` is 8-bit only. For an HDR source on `h265_vaapi`/`av1_vaapi`,
  that becomes `format=p010le,hwupload` (assuming the driver supports a
  10-bit surface for that encoder, which needs a real hardware check, not
  just an assumption from this doc).

**Known dead end: H.264 for HDR.** `h264`/`h264_vaapi` have no realistic
mainstream 10-bit/HDR delivery path. If the source is HDR and the
configured encoder is either of those, the honest answer is a codec
limitation, not a bug to paper over — worth a log line, not a workaround.

## Explicitly out of scope for this pass

- **HDR10 static metadata** (mastering display metadata, max content
  light level) — ffprobe surfaces these via `side_data_list` when
  present, but re-attaching them means formatting ffmpeg's specific
  `-master_display`/`-max_cll` string syntax from the raw probed values,
  and NVENC/av1_nvenc's actual support for *writing* that side data back
  out varies by ffmpeg version in ways I can't verify without real
  hardware. HLG doesn't need this (it's not scene-referred the way PQ
  is), so PQ content without it is still watchable, just not
  100%-spec-complete HDR10. Worth a follow-up once the primaries/transfer
  work above is confirmed working.
- **`scale_cuda` color-tag reliability specifically** — flagged above as
  a real risk, but the exact behavior is ffmpeg-build-version-dependent
  and I don't have a way to verify it without a real 5090 + the worker's
  actual ffmpeg build. The explicit `-color_primaries`/`-color_trc`/
  `-colorspace` flags are the mitigation either way (they tell the
  encoder what to write regardless of what the filter did to frame-side
  tags), but this should get an eyes-on check with real HDR footage
  before being trusted blindly.
- **VAAPI 10-bit surface support verification** — whether the actual
  render device/driver combination in use actually supports a p010
  VAAPI surface for `hevc_vaapi`/`av1_vaapi` needs checking against real
  hardware, not assumed from this doc.

## Testing notes

**Still to write, for the local path if it gets built** — these name
functions that don't exist yet, from the draft above:

- `is_hdr()`: PQ and HLG transfer values → true; missing/`bt709`/absent
  color info → false.
- `probe_color_info()`: ffprobe failure or no video stream → `None`/no
  color info, not an exception.
- `_build_ffmpeg_cmd()`: color tags present in the argv when detected,
  absent when not (no empty `-color_primaries ''` flags); HDR detection
  forces 10-bit `pix_fmt` even when the configured default is 8-bit;
  VAAPI branch swaps `nv12` for `p010le` only for
  `h265_vaapi`/`av1_vaapi`, never `h264_vaapi`.

**Already covered (manually, since `worker/` has no pytest suite - see
below), for the worker's HandBrake switch:**

- `probe_hdr_static_metadata()`: exercised against **real media**, not
  mocks - an x265-encoded file carrying mastering-display and
  content-light-level SEI returns both types, a plain file returns an
  empty set, and a probe failure returns empty rather than raising.
  This is what caught the stream-vs-frame side-data bug: the same file
  reports `NONE` under `-show_streams` and both types under
  `-show_frames`.
- `run_remux()` / `build_remux_cmd()`: real `ffmpeg -c copy` MKV→MP4 on
  both an HDR and a plain source - metadata preserved through the
  rewrap (values intact, not just presence), audio carried across,
  `+faststart` confirmed by `moov` preceding `mdat` in the output, and a
  missing input reported as `ok=False` with ffmpeg's stderr rather than
  silently passing.
- **The end-to-end container fix**, against real files: `_get_height()`
  returns `None` with empty streams for the `.mkv`, and `240` with full
  video+audio stream metadata for the remuxed `.mp4`. That is the
  difference between every remote job being rejected as invalid output
  and the pipeline working at all.
- `build_handbrake_cmd()`: produces the expected argv shape for a sample
  config (`-i <src> -o <out> -e nvenc_av1 -q N --height H
  --keep-display-aspect --encoder-preset ...`).
- `_read_handbrake_output()` (the part with the most real uncertainty,
  since HandBrakeCLI's actual live output wasn't available to test
  against): driven by a real subprocess emitting `\r`-repainted
  progress, confirming every update is picked up as it happens rather
  than buffered to exit, that the 0.99 cap holds, and that the output
  tail is captured. This also corrected an earlier misconception - the
  original version hand-rolled chunked reading and `\r` splitting on
  the belief that Python's line iteration only breaks on `\n`; text-mode
  universal-newlines translation already handles `\r`, so that buffering
  was removed rather than kept on a false premise.
- `accept()`'s container-matching (`_replace_original()`, backend-side):
  covered by a real pytest test
  (`test_accept_matches_the_candidates_container_when_it_differs`) -
  same-extension case is a documented no-op regression check, the MKV
  case verifies the rename target, `media_url` update, and old-file
  cleanup. Paired with `test_finish_renames_to_the_container_the_worker_reported`,
  which covers the upstream half that makes the MKV case reachable at
  all - without it that test would have passed against a state the real
  pipeline never produced.
- Not yet covered: `handle_job()`'s end-to-end wiring on the worker
  itself (the full claim → probe → encode → upload → finish path) -
  verified by code reading and the piece-by-piece checks above, not
  exercised end-to-end. `worker/` still has no pytest harness at all
  (unlike `backend/`) - worth setting up properly if this script keeps
  growing, especially now that it has real regex/stream-parsing logic
  worth protecting against regressions.
