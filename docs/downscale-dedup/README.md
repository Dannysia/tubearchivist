# Downscale queue dedup — deterministic doc IDs

Status: **implemented**

## Motivation

`DownscaleInteract.create()` currently keys every `ta_downscale` doc with a
random `uuid.uuid4().hex`. The only thing stopping two docs from existing
for the same video is an application-level check-then-act guard —
`get_active_for_video()` queried, then `create()` called, with nothing in
between serializing the two. The window is narrow (`create()` writes with
`refresh=true`, so it's roughly one ES round-trip), but it's real: two
near-simultaneous submissions for the same video — a double-click, or two
overlapping bulk actions — can both pass the check before either write
lands, producing two separate queued docs for one video.

The consequence today isn't corruption — `claim()`/`_reserve_slot()` both
re-run the same active-conflict check under `DISPATCH_LOCK_KEY` before
actually starting work, so a duplicate that slips through gets cleaned up
(deleted) the first time either the local runner or a remote worker
examines it. But it's still unnecessary churn, and worth closing at the
source rather than only cleaning up after.

`ta_download` (the separate download-queue index) doesn't have this
problem at all, for a structural reason: it keys every doc by the
`youtube_id` itself (see `download/src/queue.py`'s bulk `_id: video_id`
indexing, and `PendingInteract.__init__`'s `doc_id=youtube_id`). Elastic-
search's `index` write is an upsert by ID, so "adding" the same video
twice is just an idempotent overwrite of the same document — there's no
way for two rows to exist for one video, because the ID space only has
room for one. This doc proposes the same trick for `ta_downscale`.

## Key decision: key on video ID alone, not (video ID, target height)

The narrower option — key on `f"{youtube_id}_{target_height}"` — was
considered and rejected. It would only close the exact-resubmission race
(same video, same height, double-click) and leave the "two different
target heights racing for the same video" case open, since those would
get different deterministic IDs and could still coexist as separate
active docs.

Keying on video ID alone closes both at once: *any* two submissions for
the same video, regardless of target height, collide on the same
document ID. Whichever write lands last wins; there is structurally never
more than one `ta_downscale` doc for a given video.

This is also a deliberate, explicit tightening of intent: a video should
never have two downscale attempts in flight (or two competing intents) at
once, full stop — not "not at the same height." `get_active_for_video()`
already enforces exactly this at the business-rule level (it already
matches purely on `youtube_id`, not height); this change gives it a
structural backstop at the storage level instead of relying solely on the
check-then-act query.

## Behavior change worth calling out

`get_active_for_video()` only matches `queued`/`running`/`pending_review`
— it deliberately excludes `failed`, so a failed job doesn't block a
retry-shaped resubmission. Today that resubmission creates a second,
separate doc (random UUID) that sits alongside the old failed one. With a
deterministic video-ID key, the new submission's `create()` call writes
to the *same* document ID as the old failed doc and overwrites it
outright — the failed doc, its message, and its history are gone,
replaced by the fresh `queued` doc.

This seems like a net improvement (resubmitting after a failure becomes
an implicit retry instead of leaving queue clutter) rather than a
regression, but it is a real behavior change from today, worth being
explicit about rather than a silent side effect.

`get_active_for_video()` itself is **not** being removed or weakened —
it still does its own job (rejecting a new submission while a job is
genuinely active, so an in-flight running job's doc never gets clobbered
by an unrelated resubmission attempt reaching `create()`). The
deterministic ID is a second, independent guarantee — "at most one
document ever exists per video" — layered on top of "at most one *active*
job per video," not a replacement for it.

## Implementation

`DownscaleInteract.create()` (`backend/downscale/src/queue_interact.py`),
currently:

```python
def create(self, doc: dict) -> str:
    """create a new downscale job doc, return its id"""
    doc_id = uuid.uuid4().hex
    path = f"ta_downscale/_doc/{doc_id}"
    ElasticWrap(path).put(doc, refresh=True)
    self.doc_id = doc_id
    return doc_id
```

becomes:

```python
def create(self, doc: dict) -> str:
    """create a new downscale job doc, return its id. Deterministic
    (keyed on youtube_id) rather than random, so a racing duplicate
    submission for the same video overwrites the same document instead
    of creating a sibling - see docs/downscale-dedup/README.md"""
    doc_id = doc["youtube_id"]
    path = f"ta_downscale/_doc/{doc_id}"
    ElasticWrap(path).put(doc, refresh=True)
    self.doc_id = doc_id
    return doc_id
```

The now-unused `uuid` import gets dropped. No signature change, so both
existing callers (`video/views.py`'s `VideoDownscaleView.post()` and
`channel/views.py`'s bulk channel-downscale endpoint, both already
`DownscaleInteract().create(DownscaleInteract.build_queued_doc(...))`)
need no changes themselves.

Keep the plain `PUT`/upsert semantics rather than switching to ES's
`op_type=create` (fail-if-exists). A racing double-submit now has both
requests succeed, both landing on the same document — no error handling
to add anywhere, no user-facing conflict message needed, and the
overwrite is harmless since the two writes represent the same intent at
nearly the same instant.

Everything downstream of doc creation is unaffected, since nothing else
depends on the ID's *format*, only that it's a stable opaque string:

- `get_item()`/`update()`/`delete_item()` — keyed off `self.doc_id`,
  unchanged.
- `get_next_queued()`, `get_stale_leases()`, `get_active_for_video()`,
  bulk-by-filter (`views.py`'s `_get_ids_by_filter`) — all resolve IDs
  from ES search hits (`hit["_id"]`), format-agnostic.
- The remote-worker API's `source_url`
  (`/api/downscale/worker/jobs/{doc_id}/source/`) — cosmetic only.
  Django's `<str:doc_id>` path converter and ES's document-ID limits both
  handle a youtube_id-shaped string fine.

## Migration / rollout

None needed. Existing UUID-keyed docs keep their existing IDs — this only
changes how *new* docs get created going forward. Old- and new-style IDs
coexist without issue, since nothing depends on a consistent ID shape.

One transient consequence worth knowing about: until an existing
UUID-keyed doc for a given video is cleared (accepted/rejected/dismissed,
or a failed one is retried/dismissed), the "at most one doc per video"
guarantee doesn't fully apply to that video yet — a new submission would
get the deterministic ID and coexist with the old UUID-keyed leftover,
rather than overwriting it, since they're different document IDs. This
self-resolves as the pre-existing queue drains; no active backfill is
required (unlike the worker-fields backfill in
`docs/remote-downscale/ta-server.md`, which needed to run proactively
because startup logic depended on it immediately).

## Testing notes

- `create()` computes `doc_id` from `doc["youtube_id"]` — verify against
  the `ElasticWrap` path used, not by asserting on `uuid`.
- Two `create()` calls with the same `youtube_id` (different
  `target_height`, different `timestamp`) write to the same path —
  verify the second call's path matches the first's, i.e. no new-ID
  generation happens per call.
- No existing test currently exercises `DownscaleInteract.create()`
  directly (only `build_queued_doc()`, which is unaffected) — this is
  net-new coverage, not a modification of an existing assertion.

## Explicitly out of scope

- `get_active_for_video()`'s own check-then-act race (view-level check,
  then `create()`) is unrelated to this change and remains exactly as
  narrow/low-priority as before - closing *that* race would need a lock
  around the view's check+create, not a doc-ID change. This document is
  about eliminating *duplicate documents*, not about eliminating every
  race in the submission path.
- Frontend: doc_id is already treated as an opaque string by the API
  contract, so this shouldn't require frontend changes, but hasn't been
  verified against the frontend code for any UUID-shape assumptions
  (regex validation, fixed-length display truncation, etc.).
