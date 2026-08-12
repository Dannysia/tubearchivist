# Remote downscale — TubeArchivist server side

Status: **implemented**. See [README.md](README.md) for the overall
architecture and [worker.md](worker.md) for the client.

Everything here lives in the existing `backend/downscale/` app. The worker
talks plain HTTP to the existing API, authenticated with the existing DRF
token auth (`Authorization: Token …`, `AdminOnly` permission), same as any
other API client.

## Job document changes (`ta_downscale` index)

New fields on the job doc, added to the `downscale` entry in
`backend/appsettings/index_mapping.json`:

| field            | type                          | purpose |
|------------------|-------------------------------|---------|
| `worker`         | `keyword`                     | name of the remote worker holding the job; `""` for local jobs |
| `last_heartbeat` | `date` (epoch_second)         | lease renewal timestamp; only meaningful while `worker` is set |
| `progress`       | `float`, `"index": false`     | encode progress 0.0–1.0, written by heartbeats |
| `stop_requested` | `boolean`                     | set by cancel on a remote job; delivered via heartbeat response |
| `ffmpeg_args`    | `keyword`, `"index": false`   | exact argv that produced the candidate file (`shlex.join` form) |

A remote-held job is `status == "running"` with `worker != ""` and
`task_id == ""`. Local jobs keep using `task_id` and explicitly carry
`worker == ""` (never a missing field — see "Upgrade path" below for why
that distinction matters).

The video index's `downscale` block gains `ffmpeg_args` as well (see below).

## API surface

All endpoints under `/api/downscale/worker/`, `AdminOnly`. Every job-scoped
endpoint identifies the calling worker and returns **409 Conflict** if the
doc is no longer `running` or is held by a different worker — the signal
for the worker to abandon the job. That makes reaper races safe: a
reaped-and-requeued job simply rejects the old worker's late calls.

Worker identification: endpoints with a JSON body (`heartbeat`, `finish`,
`fail`) take `worker` as a required body field. Endpoints with no JSON
body — `source` (GET), `result` (PUT, raw bytes), and the `DELETE` — take
it from an `X-TA-Worker` header instead. There's no dual body-or-header
fallback on any single endpoint; each uses whichever channel actually
carries a payload.

### `POST /api/downscale/worker/claim/`

Body: `{"worker": "gaming-pc"}` (an `encoders` list may be sent for
logging/debugging; TA does not act on it).

Under the existing `DISPATCH_LOCK_KEY` Redis lock, take the oldest
`status=queued, task_id=""` job (same query as
`DownscaleInteract.get_next_queued`) and run the same validations the local
runner performs in `run()` / `_reserve_slot()`:

- video still exists in ES, source file still exists on disk
- `target_height` still below current height
- no other active job for the same video

Invalid jobs are failed/deleted exactly as the local runner would, and the
claim moves on to the next candidate. On success the doc is updated:
`status=running`, `worker`, `last_heartbeat=now`, `progress=0`,
`current_height`, `original_size`, `tmp_file_path` — mirroring what
`_reserve_slot()` writes, minus `task_id`.

Skipping many invalid candidates in one call (each doing a real `ffprobe`
subprocess call to check `current_height`) can hold `DISPATCH_LOCK_KEY`
meaningfully longer than local dispatch normally does, edging toward its
30s TTL. redis-py raises `LockError` from `release()` if the TTL already
lapsed by the time a caller gets there; a shared `_release_lock()` helper
(also used by `dispatch_pending_downscales()` and `_reserve_slot()`)
catches and logs that instead of letting it propagate — unhandled, it
would replace an already-successful claim's return value with an
uncaught 500, orphaning the job as `running` with no worker aware it has
it until the reaper eventually catches it.

Response `200`:

```json
{
  "id": "…doc id…",
  "youtube_id": "abc123",
  "title": "…",
  "target_height": 720,
  "quality_hint": 23,
  "source_url": "/api/downscale/worker/jobs/<id>/source/"
}
```

`quality_hint` is TA's configured `downscale_crf`, passed as intent only —
the worker maps quality onto its own encoder (see README "Key decisions").
Response `204` when nothing is claimable.

### `GET /api/downscale/worker/jobs/<id>/source/`

Streams the original media file. First implementation: Django
`FileResponse`. If that measurably hurts (it shouldn't for one worker on a
LAN), switch to `X-Accel-Redirect` so nginx serves the bytes after Django
authorizes the request.

### `POST /api/downscale/worker/jobs/<id>/heartbeat/`

Body: `{"worker": "gaming-pc", "progress": 0.42}`. Updates
`last_heartbeat` and `progress` on the doc. Response:

```json
{"stop": false}
```

`stop: true` when `stop_requested` is set — the worker kills ffmpeg,
discards its temp files, and `DELETE`s the job (below). Suggested worker
cadence: every 10 s; lease considered stale after 60 s (constants on the
server, see reaper).

### `PUT /api/downscale/worker/jobs/<id>/result/`

Raw video bytes in the request body, streamed to
`<tmp_file_path>.part` and renamed into place on completion. Upload and
finish are split so a connection drop mid-upload leaves no half-file that
looks complete. Requires an nginx `client_max_body_size` bump for the API
location (results can be multiple GB) — set on the `/api` block in
`docker_assets/nginx.conf`.

`tmp_file_path` is deterministic (same video + target height reuse the
same path across claims), so ownership is re-checked a second time
immediately before the rename, not just at the start of the call — a
worker whose lease got reaped-and-reclaimed mid-upload (heartbeats don't
happen during this phase for a worker that hasn't adopted the
concurrent-heartbeat pattern from `worker.md`, so a large-enough upload
can outlast the stale-lease threshold) would otherwise land its rename on
top of whatever the new claim already produced, silently corrupting it.
The re-check can't close that window to zero, but narrows it from "the
whole upload" down to a couple of ES round-trips. A cancel that arrives
mid-upload is caught by the same re-check and aborts the rename too.

### `POST /api/downscale/worker/jobs/<id>/finish/`

Body:

```json
{
  "worker": "gaming-pc",
  "encoder": "nvenc_av1",
  "quality": 24,
  "preset": "slow",
  "ffmpeg_args": "HandBrakeCLI -i … -e nvenc_av1 -q 24 …",
  "container": "mp4"
}
```

`encoder`/`preset` are recorded verbatim, in whatever vocabulary the
worker's tool uses — the shipped worker drives HandBrakeCLI, so those
are HandBrake's prefixed `nvenc_av1` and its own preset names, not
ffmpeg's `av1_nvenc`/`p5`. TA never parses them; the frontend maps both
naming conventions to the same display label
(`DownscaleEncoders.ts`). `quality` must be a whole number — the ES
mapping is an `integer`, and the worker refuses to start on a
fractional `-q` rather than discovering this after an encode.

If `stop_requested` is already set on the doc (a cancel that raced in
after the worker's last heartbeat, in the same upload/finish gap
described above), the result is discarded — same cleanup as `DELETE`
below — rather than surfacing an otherwise-valid encode for review that
the user already cancelled.

Otherwise, server behavior mirrors `_finish_success()`: probe the
uploaded file's height (reject if invalid → `failed`), record `new_size`,
store the reported encoder/quality/preset/ffmpeg_args, set
`status=pending_review`, clear `worker`/`last_heartbeat`, and call
`dispatch_pending_downscales()`. From here the job is indistinguishable
from a locally encoded one.

**`container`** is optional and carries the bare extension the worker
actually produced. A job's `tmp_file_path` is fixed at enqueue time by
`build_queued_doc()` with a hardcoded `.mp4` suffix — decided before TA
knows whether a local celery encode or a remote worker will run it — and
nothing between claim and finish revisits it: `upload_result()` streams
the body onto that same fixed path. A worker producing anything else has
to say so here, and `finish()` renames the uploaded file to match and
persists the corrected `tmp_file_path` before the job reaches
`pending_review`. The field is validated as 1–5 bare alphanumerics, so
it can only ever swap an extension, never redirect the path out of the
downscale cache directory.

**The shipped worker sends `mp4`, so this is currently a no-op.** It
exists because the worker briefly delivered `.mkv`, which does not work
— see [worker.md](worker.md)'s "Output container" for why TA cannot
store MKV, and why the worker now remuxes to MP4 before uploading. The
field is kept as a guard: if a worker ever again produces something
other than what enqueue assumed, the mismatch is recorded rather than
silently written to a misnamed file. It is not load-bearing today, and
should not be mistaken for making non-MP4 output viable on its own.

### `POST /api/downscale/worker/jobs/<id>/fail/`

Body: `{"worker": "gaming-pc", "message": "<stderr tail>"}` →
`status=failed`, clear worker fields. Message is capped to its last 2000
characters, matching the local runner's own ffmpeg-stderr cap. Same
`stop_requested` short-circuit as `finish/` above: an already-cancelled
job is discarded instead of left `failed` for a retry nobody asked for.
The existing user-facing retry re-queues a genuinely failed job normally.

### `DELETE /api/downscale/worker/jobs/<id>/`

Worker acknowledges a stop request (or abandons a job it can't finish for
local reasons): deletes the doc, same end state the local cancel path
reaches. Also calls `dispatch_pending_downscales()`.

## Lease reaper

A periodic celery beat task (registered in `task/src/task_config.py` +
`ScheduleBuilder`, e.g. every minute):

- `running` jobs with `worker != ""` and `last_heartbeat` older than the
  stale threshold, without `stop_requested` → back to `queued`, with every
  remote field reset (`worker`, `last_heartbeat`, `progress`,
  `stop_requested`) and both the tmp file and any leftover `.part`
  upload-in-progress file cleaned up (not just `DownscaleReview.requeue()`
  - that only resets `status`/`message`/`task_id`, which would leave a
  stale `worker` behind and wrongly exclude the doc from the local-only
  `count_running`/`get_interrupted` filters), then one
  `dispatch_pending_downscales()`.
- Same but *with* `stop_requested` → delete the doc and clean up both tmp
  files (the user cancelled and the worker died before acking).

Claim can additionally do a lazy sweep of stale leases before selecting a
candidate, but the beat task is the guarantee — without it, a dead worker's
job would hang in `running` until some unrelated event. **Not implemented**:
`claim()` relies solely on the beat task; it does not do this lazy sweep.

## Changes to existing behavior

### Startup auto-resume must skip remote jobs

`ta_startup._clear_downscale_leftovers()` /
`DownscaleInteract.get_interrupted()` / `requeue_interrupted()` currently
treat every `queued`/`running` doc at startup as a dead leftover. That
assumption breaks for remote jobs, which survive a TA restart. Both queries
gain a `worker == ""` filter (a local job always carries that literal
empty string, never a missing field — see the backfill migration below);
remote docs are left alone and the reaper handles them if their worker
really is gone. `count_running()` uses the same filter for the same
reason (see "Concurrency accounting" below).

### Upgrade path: backfilling `worker` on pre-existing queue docs

The local/remote distinction above only works because a local job's
`worker` field is explicitly `""`, not merely absent — an ES term query
for `worker == ""` does not match a doc where the field doesn't exist at
all. Any `ta_downscale` doc already sitting in `queued`/`running` from
before this feature shipped predates the field entirely, so left alone it
would be silently invisible to `count_running()`, `get_interrupted()`, and
`requeue_interrupted()` alike - and the lease reaper wouldn't pick it up
either, since it only looks for `worker != ""`. Nothing would ever touch
such a doc again.

`ta_startup._clear_downscale_leftovers()` therefore runs a backfill first,
via the same `_run_migration()` helper the existing `_mig_fix_*` data
migrations use (an idempotent `must_not: exists worker` `update_by_query`)
- but unlike those, it is **not** one of the numbered, `TA_MIG_SKIP_*`-
skippable migrations, since `_clear_downscale_leftovers()` runs before that
gated block and depends on the backfill having already happened. It sets
`worker=""`, `last_heartbeat=0`, `progress=0`, `stop_requested=false`, and
`ffmpeg_args=""` on any doc missing `worker`, unconditionally, every
startup (a no-op past the first run once the queue has cycled).

### Cancel path for remote jobs

`DownscaleReview.cancel()` today signals the celery task via
`TaskCommand().stop()`. For a remote-held job (empty `task_id`, `worker`
set) it instead sets `stop_requested=true` and leaves the doc in place; the
worker learns of it on its next heartbeat and acks with `DELETE`. If the
worker never acks, the reaper's stop-requested branch cleans up.

### Concurrency accounting

`downscale_max_concurrent` protects the TA host's CPU, so it must only
count local jobs: `DownscaleInteract.count_running()` gains the same
`worker == ""` filter as the startup queries, for dispatch decisions.

Pre-existing bug fixed alongside: `dispatch_pending_downscales()` does
`if max_concurrent:` — so a configured `0` is falsy and currently means
*unlimited*. New semantics: `None` = unlimited, `0` = local encoding
disabled (dispatch nothing; the natural remote-only mode). The
serializer in `appsettings/serializers.py` gets `min_value=0`.

### `accept()` matches the candidate's actual container

`DownscaleReview.accept()`'s move-and-replace step (`downscale.py`)
always renamed the candidate onto the original's existing `.mp4` path
regardless of the candidate's real extension — which would silently
produce a file with `.mp4` in its name and different bytes inside.
`_replace_original()` now compares `tmp_path`'s extension against the
original's first. Same extension (the case in practice) moves onto the
original's path exactly as before. Different extension moves onto a new
path carrying the *candidate's* extension, deletes the old original, and
updates `video.json_data["media_url"]`.

**This is a guard, not a working non-MP4 path — do not read it as one.**
Both halves of it (this and `finish()`'s `container` handling above) were
built when the worker delivered `.mkv`, on the assumption that updating
`media_url` was sufficient. That assumption was wrong. TubeArchivist is
MP4-only in places that have nothing to do with downscaling, and at
least three of them will destroy data given a non-`.mp4` `media_url`:

- `appsettings/src/filesystem.py` enumerates on-disk media as `*.mp4`
  only, so a non-MP4 video is indexed but invisible to the scanner —
  `Scanner.delete()` then treats it as a stale index entry and deletes
  the file, the ES doc, its comments, subtitles, and playlist entries.
- `video/src/index.py`'s `add_file_path()` rewrites `media_url` with a
  hardcoded `.mp4` on every reindex, and `check_reindex` is
  auto-scheduled at startup on a 90-day window — so `media_url` silently
  reverts and the real file is orphaned, with no user action involved.
- `video/src/subtitle.py` derives sidecar paths by string-replacing
  `".mp4"`, and `video/src/meta_embed.py` embeds tags through mutagen's
  MP4-specific API.

So the earlier claim here — that nothing else needed to change because
everything downstream reads `media_url` fresh from ES — was false. It is
true that those call sites read `media_url` rather than rebuilding it;
it is not true that they tolerate what they find in it.

The worker now remuxes to `.mp4` before uploading (see
[worker.md](worker.md#output-container-encode-mkv-deliver-mp4)), so
extensions match and this takes the same-extension branch every time.
Supporting a different container for real means fixing the three call
sites above first, not relying on this.

## Full ffmpeg argv (also for local encodes)

Independent of remote workers and worth shipping first:

- `DownscaleRunner._encode()` already builds the exact `cmd`; keep it on
  the instance and have `_finish_success()` persist
  `shlex.join(cmd)` as `ffmpeg_args` on the doc.
- `DownscaleReview.accept()` copies `ffmpeg_args` into
  `video.json_data["downscale"]` alongside encoder/quality/preset, and the
  `ta_video` mapping's `downscale` block gains the field
  (`keyword`, `"index": false`).
- Argv contains container-local paths; that's fine — it's a provenance
  record, not a replayable command.
- The field is named `ffmpeg_args` on both the doc and the API
  (`WorkerFinishRequestSerializer`), but the worker's remote encodes now
  run through HandBrakeCLI, not ffmpeg (see worker.md) — the field
  wasn't renamed since its documented purpose is a provenance record of
  whatever command actually produced the file, not specifically an
  ffmpeg one.

## Progress display

Remote jobs have no celery task, so no `task.send_progress` notifications.
Heartbeats write `progress` to the doc; `DownscaleListSerializer` exposes
it and `DownscaleListItem` renders a bar/percentage for running jobs.
Follow-up (phase 4): have the local runner write the same field from its
`-progress` parsing so both paths share one display mechanism.

## Testing notes

- Claim: concurrency with local dispatch (both under `DISPATCH_LOCK_KEY`),
  skip-invalid-candidate loop, per-video active exclusion, 204 on empty.
- 409 ownership checks on every job-scoped endpoint after a reap/requeue.
- Reaper: stale requeue (including `.part` cleanup), stale+stop_requested
  delete, fresh lease untouched.
- Startup sweep leaves remote-held docs alone.
- `max_concurrent=0` dispatches nothing locally but claims still succeed.
- Finish validation failure (bad upload) lands in `failed` with tmp cleaned.
- `finish()`/`fail()` discard (don't surface/retry) an already-cancelled
  job instead of proceeding normally.
- `upload_result()` aborts the rename, without renaming, when reclaimed
  or cancelled between the copy and the final ownership re-check.
- `_release_lock()` swallows an expired-TTL `LockError` on release but
  still propagates unrelated exceptions.
