# Bug backlog

Findings from the comment-stripped review of everything written since the
fork from upstream. Produced 2026-09-27 against `develop` at `142a451b`,
fork point `920b550e` (upstream/develop, 2026-08-28).

Method: the repo was copied, all comments and docstrings were stripped, all
markdown and `docs/` removed, and five subagents reviewed disjoint slices
from the code alone. Every finding was then attributed with `git blame`
against the fork point; only items rooted in post-fork code are listed here.

## How to read this

- **Verified** means checked against the real repo by hand, tracing callers
  and reading the surrounding code. **Reported** means a reviewer marked it
  CONFIRMED with a traced path, but it has not been independently checked.
- Line numbers are from `142a451b` and will drift as fixes land.
- Full per-slice reports, including the upstream-only findings and the
  "checked and found sound" lists, are outside the repo in the review
  scratchpad under `findings/`. `removed_spans.txt` there holds every
  stripped comment, to check whether a comment already answered a finding.

## Tier 1 - data loss and silent state corruption

These share one shape: an Elasticsearch write whose result is discarded,
placed after an irreversible filesystem or state change. `history.py:386`
already has the right form - it checks both the status code and
`response["errors"]` and names the failing items. A shared helper on that
pattern would close most of this tier.

### T1.1 `downscale/src/downscale.py:641` - accept() mishandles a failed ES write

**Fixed.** `accept()` probes the encode before moving it and refuses one
ffprobe returns no streams for, since `MediaStreamExtractor` runs ffprobe
with `check=False` and returns `[]` rather than raising
(`video/src/media_streams.py:29`). `upload_to_es(checked=True)` turns
`put`'s `ValueError`, a `requests` exception from an unreachable ES, or
an unexpected sub-400 status into `IndexWriteError`, and on that the job
is kept and marked failed with the reason instead of escaping as a 500.
Verified. `_replace_original` moves the encode over the original before
`video.upload_to_es()`, and `upload_to_es` is `_, _ = ElasticWrap(...).put(...)`
(`common/src/index_generic.py:68`). `put` raises `ValueError` for any
answer at or above 400 (`common/src/es_connect.py:110`), so an ES 503 or
read-only index escapes `accept()` and the bulk review loop in `views.py`
as an HTTP 500, with the encode already moved over the original, stale
`streams`/`media_size`/`media_url` in the index, the job doc still
`pending_review` for a tmp file that is gone, and the rest of the batch
unprocessed. The destructive step is ordered first, so there is nothing
to compensate from.
Fix: check the write before replacing, or make the replace recoverable.

### T1.2 `downscale/src/queue_interact.py:100` - startup sweep deletes finished encodes

**Fixed.** Paginated, and narrowed to the statuses whose files
are still needed.
Verified. `get_all_tmp_filenames()` is an unsorted `match_all` with
`size: 1000` and no pagination. `ta_startup.py:172` hands the result to
`clear_dl_cache(keep=...)` (`common/src/helper.py:231`), which deletes every
cache file not in that set. Over 1000 queued jobs, every `pending_review`
encode outside the arbitrary sample loses its output on restart and then
fails "tmp file missing". Channel-wide enqueue is uncapped
(`channel/views.py:333`), so this is routine on the ~105k-video instance.
The sibling `get_interrupted()` uses `IndexPaginate` correctly.
Fix: paginate, same as the sibling. Highest priority in this tier.

### T1.3 `common/src/queue_interact.py:30-53` - queue transitions discard ES's answer

**Fixed.** The four write methods raise `QueueWriteError` unless the
write applied, and `update` raises its subclass `QueueDocMissing` for a
document that is gone. The call sites where a failed write is survivable
catch it: the startup resume, dispatch, claim and lease reaping, the bulk
review endpoint, the stop and crash paths of a running encode, and the
pending-queue cleanup after an import or rescan. `run_queue` skips an
extraction entry that is gone and stops the run on any other failed
write, since `_get_next` matches `pending` and `extracting` alike and
would hand the same entry back forever.
Verified. `update`, `_delete_by_query` and `_update_by_query` all call
`ElasticWrap(...).post(...)` with no assignment, so a 429, 503 or missing
document is indistinguishable from success. The downscale state machine
drives every transition through `update`, and `dispatch_pending_downscales`
derives free slots from `count_running()`, which counts docs still in
`status: running`. One lost `update(status="finished")` parks that job in
`running` permanently and burns a concurrency slot; at
`downscale_max_concurrent = 1` the queue stops dispatching entirely, with
nothing connecting the stall to the failed write. The same author's
`history._upload` and `log.write_log` do check the status, so this is a gap
rather than house style.

### T1.4 `channel/src/index.py:455-463` and `:527-532` - channel delete loses its ignore rows

**Fixed.** The ignore row is written per video ahead of that video's
delete, a row that will not write keeps the video, and `_write_ignore`
raises `IndexWriteError` on a rejected status or on per-item errors
inside a 200. A delete that fails for any other reason is recorded in
`handler.failed` and reported by the task instead of ending the run.
Verified. Two distinct bugs on one path.
(a) Deletions happen per video inside the loop and are irreversible, but
`_write_ignore(to_ignore)` runs once after it, and only `FileNotFoundError`
is caught. A `PermissionError` or `OSError` from the media mount (read-only
remount, NFS/SMB stall - routine on an Unraid share) or a `TypeError` from
`del_in_playlists` on a dangling reference means line 463 never runs, and
every video deleted so far has no ignore row. `BaseTask.on_failure` only
logs. Fix: write the rows before deleting - a row for a video that then
fails to delete is harmless.
(b) `_write_ignore` reads only the HTTP status (`_, status_code = ...`) while
`_bulk` returns 200 with per-item failures, so it prints
"ignored N shorts" when nothing was written. Next channel scan
re-downloads everything.

### T1.5 `appsettings/src/filesystem.py:134` and `src/manual.py:263` - error nets narrower than what they wrap

**Fixed.** `index_new_video` now raises its `ValueError` for the `None`
return instead of dereferencing it, and both call sites catch the shared
`MEDIA_INDEX_ERRORS` tuple in `common/src/helper.py`, so the two lists
cannot drift apart again. The embed fallback reads the same unusable
file, so it is wrapped too - including the `prefer_local` call, which
was outside any handler.

The tuple's `OSError` also covers two things that are not a bad file:
`requests.RequestException`, and the builtin `ConnectionError` yt-dlp
raises on purpose on a DNS failure and on a bot block
(`download/src/yt_dlp_base.py:136,161`) to abort the task. Both are in
`NETWORK_ERRORS`, re-raised ahead of the tuple at every call site, so an
outage or a bot block stops the rescan instead of being counted against
every remaining file.

Still counted per file: an ES that is up but answering 503 or 429, because
`ElasticWrap.put` turns that into a `ValueError`, the same type as "youtube
has no metadata for this id". Telling them apart needs `put` to raise its
own type.
Verified. `ignore_error` does not hold, because the `except` clauses miss
what the upstream helpers actually raise. Three independent triggers:
- A truncated or 0-byte mp4: `index_new_video` -> `build_json` ->
  `add_player` -> `get_duration_sec` runs ffprobe with `check=True`
  (`common/src/helper.py:265`) -> `CalledProcessError`, uncaught at
  filesystem.py:134, so the rescan dies and the rest of `to_index` is never
  indexed - despite the admin having ticked `ignore_error`.
- An info.json with no top-level `"id"`: `_extract_id_from_json`
  (`manual.py:354`) raises `KeyError`, escapes `scan()`, kills the task, and
  every video queued behind it is skipped with nothing in `self.failed`.
- A video already indexed that YouTube will not serve metadata for
  (deleted, private, region-blocked): `reindex_single_video` calls
  `video.deactivate()` and returns `None` (`appsettings/src/reindex.py:408`),
  so `video/src/index.py:626` evaluates `None.json_data` and raises
  **`AttributeError`, not `ValueError`**. That bypasses the embed fallback,
  the `ignore_error` setting and the rest of the loop, and leaves the video
  flipped to `active: false`. The raising line is upstream; the `except` that
  cannot catch it is ours. This is in the code `142a451b` and `f190f018`
  most recently touched.

Fix: catch what the helpers raise. `manual.py:263` already uses
`(ValueError, CalledProcessError, OSError)` - filesystem.py should match,
plus `KeyError`, and the `None` return needs handling at the call site.

### T1.6 `download/src/extraction_queue.py:72` - a shared queue snapshot goes stale

**Fixed.** `run_queue` warmed one `PendingList` and copied `all_pending`,
`all_ignored`, `to_skip`, `all_videos` and `all_channels` into every
per-entry handler, so a 200-channel run decided what to skip from a read
taken before the first channel was extracted. Entries are paced by
`countdown_sleep` and each one extracts over the network, so that read
was hours old by the end of a long queue.

The damaging effect was not a video being skipped but one being added
back. `_parse_channel_video` (`queue.py:288`) and the playlist path
(`:329`) skip a video already in `to_skip`. Ignoring a video writes it to
`ta_download` with `status: ignore`, so before the ignore it was not in
`ta_download` at all and so not in the warm read. Ignore a video part way
through a run and the entry covering its channel re-added it as
`pending` - `add_to_pending` indexes with `_id` = the video id, so the
ignore row was overwritten. The ignore silently reverted.

Fix: `run_queue` calls `get_download` again after each entry, and a repeat
call only adds to `to_skip`, so a video a concurrent `download_pending`
finished mid run - gone from the queue, not yet in the start-of-run
`ta_video` read - stays skipped. `ta_video` is never re-read - that is the
expensive one (105k documents on the prod instance) and the reason the
warm exists at all. Cost is one paginated read of `ta_download` per entry,
against an entry that makes hundreds of yt-dlp calls.

Two related effects were left alone. Overlapping entries (two playlists
sharing videos) still re-extract the overlap, because `add_to_pending`
posts `_bulk` without `refresh=true`, so this run's own additions are not
reliably visible to the next entry's read. And `_add_video`'s `auto_start`
branch can still drop a video whose queue row was deleted between the read
and the entry; the write failure that causes is handled (T1.3), and
the common case - the row went away because `download_pending` finished
it - is correct to do nothing about.

Still open: "Delete and Ignore" on the video page (`Video.tsx:442`) during
a run. It deletes the video and queues an `ignore-force` entry; the run
processes that entry against the start-of-run `ta_video` read, which still
holds the video, so `_add_video` skips it as already indexed and no ignore
row is written. The video comes back on the next run. Outside a run the
next run's read is fresh and it works.

## Tier 2 - features that silently do not work

### T2.1 `channel/views.py:302-353` - batch channel downscale times out and reports "Queued 0"
**Fixed.** The batch runs as the `downscale_channel` task
(`downscale/src/channel_batch.py`), the view answers 202 with a task id,
and the page follows it in the channel notifications.

Verified. The POST materialises every video of the channel and per video
does one `ta_downscale/_search` plus one `_doc` PUT with `refresh=true` (a
forced Lucene refresh per document), inline in the request. `nginx.conf:56`
proxies `/api` with no `proxy_read_timeout`, so the 60s default applies. On
504 `APIClient.ts:89` cannot parse nginx's HTML and returns
`{data: undefined}`; `ChannelAbout.tsx:348` falls back to
`{queued: [], skipped: []}` and renders **"Queued 0 video(s) for
downscale."** while the backend keeps going and queues hundreds of jobs.
It also holds the sync executor for minutes, stalling other API calls.
The sibling `ChannelVideoDeleteView.delete` in the same new block does the
identical fan-out correctly: `delete_channel_videos.delay(...)` + 202 +
task_id. Fix: background it the same way.

### T2.2 `download/views.py:441-459` - "Retry Failed" on the extraction queue retries nothing
**Fixed.** The PATCH dispatches `process_extraction_queue`, and startup
dispatches it when `ExtractionQueue.has_work()` finds pending or
extracting entries.

Verified. The PATCH sets docs to `pending`, returns 204 and dispatches
nothing. `process_extraction_queue` has `api_start: False`, no beat
schedule, and is dispatched only from `tasks.py:144` and `:246`, so retried
items sit until an unrelated enqueue happens. Same stall after a crash or
restart leaves `extracting` docs that `_get_next` deliberately includes for
recovery but nothing re-runs - while `ta_startup` does resume interrupted
downscale jobs. The download-queue sibling PATCH calls
`download_pending.delay(auto_only=True)`.

### T2.3 `download/src/extraction_queue.py:92-135` - STOP deletes the in-flight entry as resolved
**Fixed.** A stop seen after `parse_url_list` puts the entry back to
`pending` and ends the run; the next run skips what was already queued.

Verified. `parse_url_list` breaks on `is_stopped` leaving `extraction_failed`
False, so `run_queue` does `resolved += 1` and `delete_item()`. A 500-video
channel stopped at 50 loses the other 450 with no failed or pending trace,
and the task reports "resolved 1".

### T2.4 `download/src/subscriptions.py:57-66` and `:97-105` - enqueue/advance is non-transactional, both results discarded
**Fixed.** `add_to_queue` raises `QueueWriteError` unless every entry
applied, so a failed enqueue stops the scan before anything advances;
`_advance_next_check` raises `IndexWriteError` the same way. Both fail
the task visibly. A re-run after a failed advance re-enqueues the same
deterministic ids, so it overwrites rather than duplicates.

Verified. A failed enqueue still advances `*_subscribed_next_check`, so one
ES 503 silently skips every subscription for a full cycle. A failed advance
is never captured at all (no assignment, no `?refresh=true`), so the
5-minute `update_subscribed` re-enqueues every subscribed channel forever.
Fails open in both directions.

### T2.5 `appsettings/src/tailscale.py:182` - exit-node rotation re-picks the current node
**Fixed.** `pick_random` excludes strictly, so a rotation with nothing
else online returns None; the bot-block rotate and the manual rotate both
report that instead of a move, and no budget is spent.

Verified. `[i for i in options if i["node_id"] != exclude_id] or options`
falls back to the node already in use when it is the only online one.
`set_exit_node` is then a no-op, but the budget is still incremented and the
user is told "rotated exit node to ... 1 of 3", and eventually "already
rotated 3 times with nothing getting through, so the block is not about this
address" - a conclusion drawn from rotations that never changed the address.
`test_sole_option_returns_that_node` locks the no-op in. Fix: compare picked
against current and report no-rotation honestly.

### T2.6 `downscale/src/worker.py:161-170` - downscale_crf is dead for remote jobs
**Fixed.** The worker ignoring it is by design
(`docs/remote-downscale/worker.md`); the defects were the unread `quality_hint` the claim sent,
`ta-server.md` saying the worker mapped it, and the settings page saying
quality applies to all future jobs. The field is gone, both docs agree,
and the page says the settings apply to jobs encoded on the server.

Verified. `downscale_crf` is read, defaulted, declared in
`WorkerClaimResponseSerializer` and sent on every claim, but
`ta_downscale_worker.py` uses `config["encode"]["quality"]` from its own
toml. The server-side CRF setting does nothing for remote jobs, and the
`quality` recorded on the doc comes from the worker. Two tests assert the
value the server just computed.

### T2.7 `task/src/notify.py:38-41` - apprise add() result discarded
**Fixed.** Only URLs apprise accepted are counted; with none it sends
nothing, and any rejected URL logs the send as `notify_failed` with the
count, without echoing the URLs.

Verified. `count = len(urls)` regardless, so one malformed URL among two
yields `(True, "notification sent to 2 url(s)")`, which the task log then
records as a `notified` event. `test()` checks the same return value.

### T2.8 `frontend/src/pages/Downscale.tsx` - three separate silent failures
**Fixed.** (a) every action, per item, selected or by filter, goes
through one path that shows the per id failures in a dismissible notice;
(b) progress falls back to the job's own `progress`, the map is only read
for a real task id, and the list refreshes every 5s while a remote job
runs; (c) changing a filter or the search resets to the first page, on
the extraction queue too.

Verified. (a) `:209-239` and `DownscaleListItem.tsx:144-197` never assign
the return of `updateDownscaleQueueByIds`/`ByFilter`;
`DownscaleBulkResultType.failed` has no reader anywhere in `frontend/src`,
and the backend returns 200 with per-id errors - so rejecting a `failed` job
looks like it worked. (b) `:31` the `DownscaleJob` type omits `progress`,
which the backend does serialize (`downscale/serializers.py:53`), and
progress is read as `progressByTaskId[job.task_id]` while worker-claimed
jobs set `task_id=""` (`worker.py:407`) - so the bar sits at 0% for the whole
encode and all worker jobs collide on the empty-string key. (c) `:279-388`
and `Extraction.tsx:89` change filters without resetting `page`, landing the
user on an empty page 4. `SettingsLogs.tsx` calls `setPage(0)` correctly.

### Tier 2 follow-ups
**Accepted** (2026-10-01): the behaviour below is acceptable as it is; not
to be fixed.
- T2.1: a stopped batch reports the same "Queued N" message as a
  finished one.
- T2.2: `has_work` reads an ES error at boot as "nothing waiting", so that
  boot does not resume the queue.
- T2.3: a stop pressed during the pacing wait after an entry fully
  finished still puts it back to pending; the next run repeats the lookup
  only to skip every video.
- T2.4: `extrac_dl` raising on a partial bulk skips dispatching the entries
  that did land, and a failed channel scan now skips that cycle's playlist
  scan too.
- T2.5: "no other mullvad exit node" is also the wording when there is no
  current exit node at all.
- T2.8: the 5s refresh while a remote job runs also reloads the three
  aggregation queries.

## Tier 3 - dead code that would mislead a future reader

### T3.1 `common/src/history.py:432-587` - the entire read side has no caller
Verified. `HistoryQuery`, its six query methods, `decode_change` and
`decode_value` are referenced only by `test_history.py`. No route, no
serializer, no frontend. The write side runs on every reindex and
`ta_history` is in the backup set, but nothing prunes it (`prune_logs`
covers `ta_log` only), so it grows forever. Live footgun: `build_query`
returns `{"match_all": {}}` with no filters (line 485), so
`HistoryQuery().delete()` wipes the index.
**Decided** (2026-09-30): keep writing history; reading it is a separate UX
project, not part of the bug bash.

### T3.2 `downscale` container escape hatch is unreachable and destructive
**Fixed** (container handling removed - MKV never leaves the worker).
Reported. Serializer field, 13 lines of help text, `_match_uploaded_container`
and `_replace_original`'s extension branch, all tested - but the only worker
always sends `"mp4"`. A worker sending `"mkv"` would hit `_get_height` ->
`_extract_video_metadata`'s `bit_rate` gate -> `None` -> file deleted, job
"failed - output is invalid". Every media path in the backend is hardcoded
`.mp4` and `mutagen.mp4.MP4` is used unconditionally, so non-mp4 would break
more than `_get_height`. `test_finish_renames_to_the_container_the_worker_reported`
passes only because `_get_height` is mocked.

### T3.3 `downscale/src/downscale.py:420-428` - max_concurrent = 0 traps jobs forever
**Fixed.** `_reserve_slot` hands a dispatched job back to the queue with an
empty `task_id` when local encoding is off, so a remote worker can claim it.

Verified. `_reserve_slot` has no zero case, unlike
`dispatch_pending_downscales:287`. `count_running() >= 0` always retries,
`max_retries=None` (`task/tasks.py:432`) means it never gives up, and
`task_id != ""` keeps the job invisible to `claim()`. Only a restart clears
it. A test pins this as intended without noticing the wait cannot end.

### T3.4 Aggregations turn an ES error into a 200 of zeros
**Fixed.** `AggBase.get()` and both channel aggregations raise
`SearchUnavailable` on a failed search, which DRF answers as a 503 with an
`error` body. The empty fallbacks in the fork's classes are gone, and with
them `empty_resolution`/`empty_transitions`, which only fed them. Upstream's
own `if not aggregations` checks are left in place, now unreachable.

Verified. `channel/src/aggs.py:94,282` and `stats/src/aggs.py:431,520` all
do `response, _ = ...` and then `if not aggs: return self._empty()`. ES
always returns `aggregations` for a successful `size: 0` search, so that
branch is reachable only on an error body - the helper is named for the case
that cannot happen and absorbs the case that does. A channel with thousands
of videos then reports "0 videos, 0 bytes, no date range" with HTTP 200.

### T3.5 Smaller dead items
**Fixed**, all seven. The worker-name JSON branch was reachable for the
DELETE view, but no client uses it: both the current worker and the one at
142a451b send `X-TA-Worker`. The `except Retry` wrapper in `download_pending`
is upstream's and stays.

- `status="cancelled"` appears in three ChoiceFields and the UI dropdown but
  no code path ever writes it.
- `channel/src/index.py:214-233` `_wait_for_next_playlist`'s "no task" path
  cannot run: `index_channel_playlists` dereferences `self.task` unguarded
  before the loop.
- `downscale/worker_views.py` `_get_worker_name`'s JSON branch is
  unreachable and `parser_classes=[]` would make it raise; 2 of 3 tests in
  `test_worker_views.py` cover only it.
- `encoders` is validated then discarded, though the help text says it is
  logged.
- Empty `ids: []` on the downscale bulk endpoint falls through to an
  unfiltered 1000-doc `match_all`; today all call sites are gated.
- `except Retry as exc: raise exc` (`task/tasks.py:211`) wraps a try with no
  other handler.
- `video/src/resolution.py:55` tier filters are correct only because
  `DOWNSCALE_LADDER` is descending and nothing asserts it. One
  `assert DOWNSCALE_LADDER == sorted(..., reverse=True)` pins it.

## Tier 4 - UI

### T4.1 `frontend/src/components/ChannelList.tsx:76-100` - non-admins see Subscribe and get logged out
**Fixed.** Both buttons are behind `isAdmin`, as in `ChannelOverview`.

Verified, and the whole button block is ours (2026-09-02). `POST
/api/channel/<id>/` is `AdminWriteOnly` -> 403, and `APIClient.ts:73` treats
any 403 as a dead session: `logOut(); window.location.href = Routes.Login`.
`ChannelOverview.tsx:162` wraps the identical pair in `isAdmin &&`.

### T4.2 Reset on two settings can only ever fail
**Fixed.** Both accept null, which their readers already treat as the
default; the log cleanup reports the retention it actually used.

Verified. Upstream `InputConfig.tsx:120` offers reset whenever the value is
not null and posts `null`. `log_retention_days`
(`appsettings/serializers.py:116`) and `max_exit_node_rotates` (`:71`) are
the only new settings without `allow_null=True`, so both always 400 with
"the value was rejected". Every other new setting - `frequency_hours`,
`jitter_percent`, `downscale_max_concurrent`, `downscale_crf`,
`downscale_preset` - is nullable.

### T4.3 `frontend/src/pages/SettingsActions.tsx:64-69` - import refresh fires ~1s in, never at completion
**Fixed.** The import refresh and the Start button wait for `isDone`.

Reported. The handler declares no parameter and sits inside an upstream
callback that fires on every notification tick, so the first tick clears
`processingImports` (making "Start import" clickable mid-run) and refreshes
a folder nothing has consumed. `Channels.tsx:171`, `Download.tsx:181` and
`Playlists.tsx:147` all branch on `isDone`.

### T4.4 Smaller UI items
**Fixed**, all five. The filter counts are faceted: each applies every
active filter except its own. The search keeps refetching per keystroke
but a superseded answer is dropped.

- `Downscale.tsx:89` filter dropdown counts ignore every other active
  filter, so a count can name more jobs than selecting it will show.
- `Downscale.tsx:115` queue search refetches per keystroke with no debounce
  and no ordering guard; a late earlier response can overwrite a newer list.
- `SettingsDashboard.tsx:77` two new `await`s extend a pre-existing fake
  `Promise.all` - 11 strictly serial requests, and the two additions are the
  heaviest full-index aggregations.
- `SettingsLogs.tsx:218` "Could not read the log" only fires on a JSON parse
  failure, so a DRF-shaped 404/405/throttle is stored as data and the page
  says "Nothing logged yet".
- `loadExtractionQueue.ts:18` double-encodes `q` and nothing sets it.

### Tier 3 and 4 follow-ups
**Accepted** (2026-10-01): acceptable as it is; not to be fixed.
- T3.4: a stats panel whose search fails now gets a 503 instead of zeros,
  but the dashboard and the channel page render any failed panel as
  "Loading..." indefinitely - the same as upstream's panels on any failed
  fetch. A real "could not load" state is UI work across those components.

## Tier 5 - other in-scope bugs

- **Audited, no change.** `common/src/index_generic.py` - `upload_to_es()`
  takes a `checked` flag that only `DownscaleReview.accept()` passes. The
  premise that the other 21 callers discard the status does not hold:
  `ElasticWrap.put` raises `ValueError` for any answer at or above 400 and
  `upload_to_es` re-raises it unchecked, so every caller already fails on
  a failed write. `checked` adds only its own exception type and a check
  on sub-400 statuses ES does not return for an index PUT. Flipping the
  default would change the type to `IndexWriteError` under three callers
  that catch `ValueError` - the manual import and filesystem rescan
  per-file nets, and `channel/src/index.py:259` - turning a failed write
  there from a per-item failure into an aborted task. That is the open
  T1.5 question of telling an ES outage from a bad file, and belongs with
  it rather than with a default flip.
- **Fixed.** `appsettings/src/backup.py:28` - the new `"history": 10000` entry feeds an
  unpruned index through `IndexPaginate`, which accumulates every hit with
  full `_source` regardless of the callback. After an OOM kill the loose
  `es_*.json` stay in `BACKUP_DIR` and the next `zip_it` globs any `*.json`
  into an unrelated archive that a later restore applies.
- **Fixed.** `appsettings/src/manual.py:787-809` - `validate_name` accepts uppercase
  extensions (a test blesses `.MP4`), but `_convert_video` compares
  `ext == ".mp4"` case-sensitively, so a correct mp4 is fully re-encoded and
  the original deleted. `.MKV` misses `_dump_thumb`'s branch.
- **Fixed.** `appsettings/src/manual.py:231-239` - the orphan-sidecar report misses the
  last group: groups finished inside the loop are appended unconditionally,
  the final one only `if current_video.get("media")`. Staging a lone
  `.info.json` yields a "successful" run that imported nothing.
- **Fixed.** `appsettings/views.py:478-484` - a disk-full multi-file upload raises
  `OSError`, the view catches only `ValueError` -> 500 and a half-staged
  batch. The sibling metadata endpoint catches `(ValueError, OSError)`.
- **Fixed.** `download/src/queue.py:240-242` - the new `extraction_failed` tracking
  misses the "no videos from channel" return, so a failed listing is deleted
  as resolved after `next_check` has moved. The fork added the flag to the
  three adjacent branches and missed this one.
- **Fixed in T2.4.** `download/src/extraction_queue.py` `add_to_queue` returns `len(entries)`
  whenever `_bulk` answers 200, even when individual bulk items errored, so
  the reported add count can overstate what was indexed. Same T1 family as
  T1.4b - a `_bulk` 200 is not an all-items-succeeded signal.
- **Fixed.** `download/src/queue.py:128,385,401` - `videos_failed_count` is incremented
  and never read; with `track_failure=False` for channel/playlist videos it
  is the only record, so 50/50 videos failing still reports "resolved 1".
- **Fixed.** `task/src/config_schedule.py:66-67` - no task-name validation. An unknown
  name with `"auto"` raises `KeyError` -> 500 instead of 404; a known but
  unschedulable task (`manual_import`) gets a real periodic task that beat
  then calls without its required args every interval.
- **Fixed.** `task/tasks.py:206-209` - `process_extraction_queue`'s retry cannot retry:
  `mark_failed` writes `status: failed` while `_get_next` queries only
  `pending|extracting`. Also missing the `and not self.is_stopped()` guard
  its sibling has.
- **Fixed.** `channel/src/list_query.py:94-106` - the 10000-channel ceiling truncates
  silently and reports exactly 10000 as the total; ES's `relation: "gte"` is
  discarded. Low severity at current scale.
- **Fixed** (with T1.6's per-entry re-read). `download/src/extraction_queue.py:116` - `to_skip` is re-copied per entry,
  so a video reachable from two entries is fully re-extracted.
- **Fixed** (worded as entries). `task/tasks.py:145-147` - "Found N channels/playlists" counts one entry
  per channel per tab.
- **Fixed.** `download/src/extraction_queue.py` `run_queue` warms three full-index
  scans, including all of `ta_video` with no `_source` filter, before
  checking whether the queue has work; `extrac_dl` dispatches it
  unconditionally. On the ~105k-video box that is a full scroll for nothing,
  under `--max-memory-per-child 150000`.
- **Accepted** (2026-10-01). Failed video entries from a channel or
  playlist scan share `_build_id` with entries queued by hand, so a bare
  `/@handle` channel scan and a plain watch URL for the same video both map
  to `video_<id>_unknown`, and the failed entry replaces the queued one.
  The latest extraction error is the more useful state to keep.
- **Accepted** (2026-10-01). A rate-limited full scan (429s, timeouts)
  lists each video it could not extract as its own failed entry, so a
  large first scan can leave hundreds of them.

## Tests that pass for the wrong reason

- **Fixed.** `video/tests/test_src/test_resolution.py:105-117` - both "reconcile" tests
  build their input from the expected answer via `build_response(counts)`, so
  they hold whether or not the tiers are exclusive and exhaustive, which is
  the property the names claim.
- **Fixed.** `task/tests/test_src/test_config_schedule.py:134` -
  `orphaned_schedules(TASK_CONFIG.keys(), TASK_CONFIG)` is `set(x) - set(x)`.
- **Fixed.** `common/tests/test_src/test_countdown_sleep.py:161-172` - parametrises
  `[None, 0]` then hardcodes `set_interval(monkeypatch, 0)`, so both cases
  are identical and the `None` branch stays untested.
- **Fixed with T3.3.** `test_max_concurrent_zero_blocks_a_local_job_that_still_got_dispatched`
  pins T3.3 as intended behaviour without noticing the wait cannot end.

## Rejected - do not re-raise

- **`filesystem.py:114` `_index_one` "returns False on success"** is not a
  bug. The return value means "should the caller pace afterwards", not
  "did it succeed", and `if not self._index_one(...): continue` correctly
  skips the rate-limit wait for the local-embed path. The reviewer saw this
  only because the docstring stating it had been stripped.
- **`run_tests.sh` leaving a root-owned `.pytest_cache` that dirties the
  tree** is not real. `backend/.pytest_cache` is user-owned, and pytest
  writes its own `.gitignore` containing `*`, so the directory self-ignores;
  `git check-ignore` confirms. No `-dirty` image tags result.

## Not a bug

The `application` log source (`common/src/log.py:20`,
`common/serializers.py:199`, `loadLogs.ts:4`) is plumbed through and
accepted by the backend but only ever written with `source="notification"`.
This is a deferred feature, not dead code. Leave it.

## Upstream bugs that still affect this install

Not our code, so out of scope for the cleanup, but real where we run it:
`playlist/src/index.py:475` `get_video_index` returns `-1` and `move_video`
uses it as an index, so reordering or removing a video that is not in the
playlist mutates the last entry instead (empty custom playlist -> 500);
`video/src/index.py:116` `post_timestamps`/`vote_on_segment` return a
hard-coded `{"success": True}` without contacting SponsorBlock, and their
`get_sb_id` raises `KeyError` because `sponsorblock_id` is not a permitted
user-config key; clearing a channel overwrite with `null` persists an
explicit `null` that `_check_get_sb` reads as "SponsorBlock off";
`task/views.py:280,350` notification endpoints inherit `IsAuthenticated`
rather than `AdminOnly` while every neighbour is admin-only;
`download/src/queue.py:224` reads
`self.force and url in self.all_ignored or url in self.all_pending`, which
binds as `(force and in all_ignored) or (url in all_pending)` and compares
a string against a list of dicts, so the second half is always false and
the force path never sees an entry already queued;
`download/src/queue.py:91` `_map_overwrites` builds `video_overwrites`,
which nothing anywhere reads;
`stats/src/aggs.py:335` `BiggestChannel.__init__` mutates the class-level
`data` dict; `appsettings/src/filesystem.py:95` `Scanner.delete` calls
`delete_media_file()` in a bare loop, so the first video that will not
delete abandons every remaining one, the same shape as T1.4 but in
upstream code. The per-slice reports list the rest.
