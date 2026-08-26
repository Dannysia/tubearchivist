# Metadata history

Records what changed on a video, channel or playlist every time its
metadata gets refreshed, so the previous values stay queryable after the
document itself has been overwritten.

This is the data layer only — nothing is exposed over the API or the
frontend yet.

## Storage

One Elasticsearch document per **changed field per refresh**, in the
`ta_history` index (declared in `backend/appsettings/index_mapping.json`,
so it is created, backed up and snapshotted like every other index).

```json
{
  "item_id": "dQw4w9WgXcQ",
  "item_type": "video",
  "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
  "refresh_id": "7f3a1c...",
  "source": "reindex",
  "timestamp": 1756100000,
  "field": "stats.view_count",
  "old_value": "1412000",
  "new_value": "1498231",
  "old_value_type": "number",
  "new_value_type": "number",
  "old_num": 1412000.0,
  "new_num": 1498231.0,
  "delta": 86231.0
}
```

- `field` is the dotted path into the indexed document.
- `refresh_id` groups every field that changed in the same refresh.
- `source` is `reindex` for a scheduled/manual refresh, `redownload`
  when the refresh came from a forced re-download.
- `old_num` / `new_num` / `delta` only exist for numeric values, which
  is what makes a view count series a plain `sort` or `date_histogram`.
- `*_value_type` is one of `string`, `number`, `bool`, `json`, `null`,
  `missing`, and tells the reader how to decode `*_value`. Strings are
  stored raw, everything else is JSON encoded. `missing` means the field
  was not on the document at all — a metadata field disappearing
  upstream is itself history worth keeping.
- The document `_id` is `{item_id}-{timestamp}-{field}`, so replaying
  the same refresh overwrites rather than duplicating.

`old_value` / `new_value` are mapped as `text` with `index: false`: they
are payload, not something to search on. Filtering happens on `item_id`,
`item_type`, `channel_id`, `field`, `source` and `timestamp`.

## Tracked fields

Defined in `TRACKED_FIELDS` in `backend/common/src/history.py`.

| Type | Fields |
| --- | --- |
| video | `title`, `description`, `category`, `tags`, `published`, `vid_type`, `active`, `stats.view_count`, `stats.like_count`, `stats.dislike_count`, `stats.average_rating`, `vid_thumb_url` |
| channel | `channel_name`, `channel_description`, `channel_subs`, `channel_tags`, `channel_tabs`, `channel_active`, `channel_thumb_url`, `channel_banner_url`, `channel_tvart_url` |
| playlist | `playlist_name`, `playlist_description`, `playlist_channel`, `playlist_channel_id`, `playlist_active`, `playlist_thumbnail`, `playlist_entry_count` |

Three comparison normalizations keep the noise out:

- **lists** (`tags`, `category`, `channel_tags`, `channel_tabs`) compare
  order independently — yt-dlp does not return a stable order.
- **image urls** compare on host + path only. YouTube rotates the `sqp`
  and `rs` signing params on every extraction; real new artwork gets a
  new path.
- **`published`** compares as a UTC calendar date. `_build_published()`
  stores an epoch int when yt-dlp supplies a `timestamp` and a
  `YYYY-MM-DD` string when it only has `upload_date`, so the raw values
  can flip representation without the date moving. Measured exposure on
  a 105k video library: 0.2% of documents hold the string form, and they
  correlate with *recent* downloads rather than old ones — so this is
  not the yt-dlp version drift it looks like, and the normalizer is
  cheap insurance rather than a fix for a widespread problem.

Note on omissions: `comment_count` is deliberately not tracked. It is
written back only *after* the video document is re-indexed, so tracking
it would record a bogus removal on every single refresh. The same
applies to anything else not produced by `build_json`.

### Volume

Measured at ~388 bytes per document in ES (worst case: a numeric change
with every field populated and random high-cardinality ids, so real data
compresses better).

`_get_daily_should()` budgets `(total // interval + 1) * 1.2` items a
day, but that is a ceiling: `_get_outdated_ids()` only spends it on
documents actually past `interval` days old. In steady state just
1/interval of the library crosses that line each day, so every video is
refreshed 365/interval times a year - about 4 times at the 90 day
default. The 1.2 is catch-up headroom for a backlog, not a rate.

`view_count` changes on virtually every refresh and `like_count` on
most, so the stats fields dominate the volume:

| Library | Docs/year | Storage/year |
| --- | --- | --- |
| 1,000 | ~8k | ~3 MB |
| 10,000 | ~80k | ~30 MB |
| 110,000 | ~750k | ~290 MB |

Shortening the reindex interval scales all of this linearly.

Roughly double that with `integrate_ryd` enabled, which adds
`dislike_count` and `average_rating` to the churn.

Non-numeric changes — retitles, description edits, tag changes,
deletions — are perhaps 2-3% of refreshes, so a couple of percent of the
volume even though individual docs are fatter. Dropping the `stats.*`
specs from `TRACKED_FIELDS` therefore cuts storage ~50x while keeping
every metadata edit. That is the lever if volume ever becomes a problem.

None of this is close to an Elasticsearch limit — a single shard handles
tens of millions of documents — but it does grow monotonically, see
"not wired up" below.

## Write path

`backend/appsettings/src/reindex.py` compares the pre-refresh state it
already holds (`es_meta`) against the rebuilt document, immediately
before `upload_to_es()`:

- `Reindex.reindex_single_video` — and `track_deactivation` when YouTube
  no longer serves the video.
- `Reindex._reindex_single_channel` — same for a dead channel.
- `Reindex._reindex_single_playlist` — `es_meta` is captured before
  `update_playlist()`, which rebuilds and uploads in one go.

`track_changes()` never raises: losing a history row must not fail an
indexing run. Failures print and return `[]`.

## Read path

`HistoryQuery` in `backend/common/src/history.py`:

```python
from common.src.history import HistoryQuery

# everything that changed on one video, newest first
HistoryQuery(item_id="dQw4w9WgXcQ").get_changes()

# grouped per refresh
HistoryQuery(item_id="dQw4w9WgXcQ").get_refresh_events()

# view count over time, oldest first
HistoryQuery(item_id="dQw4w9WgXcQ").get_field_series("stats.view_count")

# every retitle across the library in the last week
HistoryQuery(item_type="video", fields=["title"], since=since_ts).get_changes()

# which fields have history, with counts
HistoryQuery(item_id="dQw4w9WgXcQ").get_tracked_fields()
```

All readers return values already decoded back to python types via
`decode_change()`.

## Verified

Exercised end to end against a live instance through
`POST /api/refresh/` → celery → `Reindex`:

- **video** — stats deltas, a real `vid_thumb_url` jpg→webp migration,
  and a second refresh a minute later writing exactly one row (the view
  tick) and nothing for the eight unchanged fields.
- **channel** — `channel_subs` change, `channel_id` self-denormalized.
- **playlist** — the stored document was perturbed to simulate upstream
  drift, then refreshed: name change recorded, `playlist_description`
  recorded as `string → missing` with the old text preserved,
  `playlist_entry_count` recorded from the derived getter, and a
  thumbnail whose `sqp`/`rs` params alone had changed correctly recorded
  *nothing*. This also confirms the `es_meta`-before-`update_playlist()`
  ordering captures the pre-refresh state.

Not yet exercised against real data: the deactivation paths, and
behaviour at full library scale. Both fail safe — a missing history row,
never a broken reindex.

## Not wired up

- **Deletion.** `HistoryQuery(item_id=...).delete()` exists but is not
  called when a video/channel/playlist is removed, so history outlives
  the item. Flip that if orphans are not wanted.
- **Retention.** Nothing prunes `ta_history`.
- **Config toggle.** Tracking is always on, there is no app setting.
- **`ChannelFullScan`.** Runs at the end of a channel reindex and fixes
  `vid_type` mismatches with a direct `_bulk` update to `ta_video`,
  bypassing `YoutubeVideo` entirely, so those corrections are not
  recorded. The old values are available in `_get_all_local()` if this
  is ever worth wiring up.

## Querying `timestamp`

`timestamp` is mapped `epoch_second`, and the two directions do not
behave the same way:

- **indexing** a bare number honours the field's format, so the int
  written by `HistoryTracker` stores correctly (`1787728862` decodes to
  `2026-08-26T07:21:02Z`).
- **range queries** ignore it and read a bare number as epoch **millis**,
  so an int cutoff resolves to some date in 1970 and silently matches
  nothing rather than erroring.

`HistoryQuery.build_query()` therefore declares `"format":
"epoch_second"` on the range, which keeps it correct whether an int or a
string arrives. Anything new that filters on `timestamp` must do the
same. The backend already carries three other mitigations for this —
`str()` in `ReindexPopulate._get_outdated_ids` and the autodelete
queries, ISO date strings in `add_recent()`, `"now-7d/d"` date math in
the stats aggs, and the same explicit format in `DownscaleInteract`'s
`last_heartbeat` range. All are correct; the explicit format is the one
that does not depend on the caller's type.

## Failure handling

`track_changes()` swallows everything and returns `[]` — a lost history
row must never fail an indexing run. Write failures are reported two
ways, because `_bulk` answers `200` even when individual documents are
rejected: a bad status code prints the response, and a `200` carrying
`"errors": true` prints the per document errors.
