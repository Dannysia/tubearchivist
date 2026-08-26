"""
functionality:
- track metadata changes of videos, channels and playlists over time
- write one ta_history document per changed field
- read back the recorded history for a single item or field
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from common.src.es_connect import ElasticWrap, IndexPaginate

ItemType = Literal["video", "channel", "playlist"]
ValueType = Literal["string", "number", "bool", "json", "null", "missing"]

INDEX_NAME = "ta_history"

ACTIVE_KEYS: dict[str, str] = {
    "video": "active",
    "channel": "channel_active",
    "playlist": "playlist_active",
}


class Missing:
    """sentinel for a field that is not present in a document at all"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)

        return cls._instance

    def __repr__(self):
        return "<missing>"


MISSING = Missing()


def _path_getter(dotted: str) -> Callable[[dict], Any]:
    """build getter for a dotted path, MISSING if not found"""
    keys = dotted.split(".")

    def getter(doc: dict) -> Any:
        current: Any = doc
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return MISSING

            current = current[key]

        return current

    return getter


def _entry_count_getter(doc: dict) -> Any:
    """derive playlist entry count"""
    entries = doc.get("playlist_entries", MISSING)
    if entries is MISSING or entries is None:
        return MISSING

    return len(entries)


def _sorted_list(value: Any) -> Any:
    """normalize list for comparison, reordering is not a change"""
    if not isinstance(value, list):
        return value

    return sorted(json.dumps(i, sort_keys=True) for i in value)


def _published_date(value: Any) -> Any:
    """
    normalize a published date for comparison. _build_published stores an
    epoch int when yt-dlp hands over a `timestamp` and a YYYY-MM-DD
    string when it only has `upload_date`, and which one YT serves for a
    given video is not stable across yt-dlp versions. Comparing the raw
    values would record a change every time the representation flips
    without the publish date actually moving, so both sides are reduced
    to a UTC calendar date.
    """
    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = float(value)
        except (TypeError, ValueError):
            # already a date string, keep the date part only
            return value[:10]
    else:
        return value

    try:
        return (
            datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        )
    except (OverflowError, OSError, ValueError):
        return value


def _stable_url(value: Any) -> Any:
    """
    normalize an image url for comparison. YT rotates signing query
    params (sqp, rs) on every extraction without the image itself
    changing, so only host and path are compared. A new artwork gets a
    new path, which is what should register as a change.
    """
    if not isinstance(value, str) or not value:
        return value

    split = urlsplit(value)

    return f"{split.netloc}{split.path}"


@dataclass(frozen=True)
class FieldSpec:
    """describes a single tracked field"""

    name: str
    getter: Callable[[dict], Any]
    normalize: Callable[[Any], Any] | None = None

    def extract(self, doc: dict | None) -> Any:
        """get raw value from document"""
        if not doc:
            return MISSING

        return self.getter(doc)

    def comparable(self, value: Any) -> Any:
        """normalize raw value for equality check only"""
        if value is MISSING or self.normalize is None:
            return value

        return self.normalize(value)


def _spec(
    dotted: str,
    normalize: Callable[[Any], Any] | None = None,
) -> FieldSpec:
    """build FieldSpec from a dotted path"""
    return FieldSpec(
        name=dotted, getter=_path_getter(dotted), normalize=normalize
    )


# fields compared on every refresh, per item type.
# note on omissions: video.comment_count is rebuilt only after the video
# doc is written back, tracking it would record a bogus removal on every
# single refresh. Same reasoning for anything else not produced by
# build_json/process_youtube_meta.
TRACKED_FIELDS: dict[str, list[FieldSpec]] = {
    "video": [
        _spec("title"),
        _spec("description"),
        _spec("category", normalize=_sorted_list),
        _spec("tags", normalize=_sorted_list),
        _spec("published", normalize=_published_date),
        _spec("vid_type"),
        _spec("active"),
        _spec("stats.view_count"),
        _spec("stats.like_count"),
        _spec("stats.dislike_count"),
        _spec("stats.average_rating"),
        _spec("vid_thumb_url", normalize=_stable_url),
    ],
    "channel": [
        _spec("channel_name"),
        _spec("channel_description"),
        _spec("channel_subs"),
        _spec("channel_tags", normalize=_sorted_list),
        _spec("channel_tabs", normalize=_sorted_list),
        _spec("channel_active"),
        _spec("channel_thumb_url", normalize=_stable_url),
        _spec("channel_banner_url", normalize=_stable_url),
        _spec("channel_tvart_url", normalize=_stable_url),
    ],
    "playlist": [
        _spec("playlist_name"),
        _spec("playlist_description"),
        _spec("playlist_channel"),
        _spec("playlist_channel_id"),
        _spec("playlist_active"),
        _spec("playlist_thumbnail", normalize=_stable_url),
        FieldSpec(name="playlist_entry_count", getter=_entry_count_getter),
    ],
}


def encode_value(value: Any) -> tuple[Any, ValueType, float | None]:
    """
    encode a python value for storage,
    returns stored value, value_type and numeric representation
    """
    if value is MISSING:
        return None, "missing", None

    if value is None:
        return None, "null", None

    if isinstance(value, bool):
        return json.dumps(value), "bool", None

    if isinstance(value, (int, float)):
        return json.dumps(value), "number", float(value)

    if isinstance(value, str):
        return value, "string", None

    return json.dumps(value, sort_keys=True), "json", None


def decode_value(stored: Any, value_type: str | None) -> Any:
    """reverse encode_value, MISSING stays a sentinel"""
    if value_type == "missing":
        return MISSING

    if value_type in (None, "null", "string"):
        return stored

    try:
        return json.loads(stored)
    except (TypeError, ValueError):
        return stored


def decode_change(source: dict) -> dict:
    """decode a raw history document into python values"""
    decoded = source.copy()
    decoded["old_value"] = decode_value(
        source.get("old_value"), source.get("old_value_type")
    )
    decoded["new_value"] = decode_value(
        source.get("new_value"), source.get("new_value_type")
    )

    return decoded


class HistoryTracker:
    """diff two states of a document and store the changed fields"""

    def __init__(
        self,
        item_type: ItemType,
        item_id: str,
        source: str = "reindex",
        timestamp: int | None = None,
    ):
        self.item_type = item_type
        self.item_id = item_id
        self.source = source
        self.timestamp = timestamp or int(datetime.now().timestamp())
        self.refresh_id = uuid4().hex

    def track(self, old: dict | None, new: dict | None) -> list[dict]:
        """build and store changes, returns what got written"""
        changes = self.build_changes(old, new)
        if changes:
            self._upload(changes)

        return changes

    def build_changes(self, old: dict | None, new: dict | None) -> list[dict]:
        """build change documents, does not touch es"""
        specs = TRACKED_FIELDS.get(self.item_type)
        if specs is None:
            raise ValueError(f"unexpected item_type: {self.item_type}")

        if not old and not new:
            return []

        channel_id = self._get_channel_id(old, new)
        changes = []
        for spec in specs:
            old_value = spec.extract(old)
            new_value = spec.extract(new)
            if spec.comparable(old_value) == spec.comparable(new_value):
                continue

            changes.append(
                self._build_doc(spec.name, old_value, new_value, channel_id)
            )

        return changes

    def _get_channel_id(
        self, old: dict | None, new: dict | None
    ) -> str | None:
        """denormalize channel id to filter history by channel later"""
        if self.item_type == "channel":
            return self.item_id

        for doc in (new, old):
            if not doc:
                continue

            if self.item_type == "video":
                value = (doc.get("channel") or {}).get("channel_id")
            else:
                value = doc.get("playlist_channel_id")

            if value:
                return value

        return None

    def _build_doc(
        self,
        field_name: str,
        old_value: Any,
        new_value: Any,
        channel_id: str | None,
    ) -> dict:
        """build a single change document"""
        old_stored, old_type, old_num = encode_value(old_value)
        new_stored, new_type, new_num = encode_value(new_value)
        doc = {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "channel_id": channel_id,
            "refresh_id": self.refresh_id,
            "source": self.source,
            "timestamp": self.timestamp,
            "field": field_name,
            "old_value": old_stored,
            "new_value": new_stored,
            "old_value_type": old_type,
            "new_value_type": new_type,
        }

        if old_num is not None:
            doc["old_num"] = old_num
        if new_num is not None:
            doc["new_num"] = new_num
        if old_num is not None and new_num is not None:
            doc["delta"] = new_num - old_num

        return doc

    def _build_doc_id(self, field_name: str) -> str:
        """
        deterministic id, so replaying the same refresh is idempotent
        rather than duplicating rows
        """
        return f"{self.item_id}-{self.timestamp}-{field_name}"

    def _upload(self, changes: list[dict]) -> None:
        """bulk index changes"""
        bulk_list = []
        for change in changes:
            action = {
                "index": {
                    "_index": INDEX_NAME,
                    "_id": self._build_doc_id(change["field"]),
                }
            }
            bulk_list.append(json.dumps(action))
            bulk_list.append(json.dumps(change))

        # add last newline
        bulk_list.append("\n")
        data = "\n".join(bulk_list)
        response, status_code = ElasticWrap("_bulk").post(
            data=data, ndjson=True
        )
        if status_code not in [200, 201]:
            print(f"{self.item_id}: failed to write history: {response}")
            return

        if response.get("errors"):
            # a 200 from _bulk still reports per document failures
            failed = [
                i["index"]["error"]
                for i in response.get("items", [])
                if i.get("index", {}).get("error")
            ]
            print(f"{self.item_id}: history write errors: {failed}")


def track_changes(
    item_type: ItemType,
    item_id: str,
    old: dict | None,
    new: dict | None,
    source: str = "reindex",
) -> list[dict]:
    """
    compare old and new state of a document and store changed fields.
    Never raises, losing history must not fail an indexing run.
    """
    # pylint: disable=broad-except
    try:
        tracker = HistoryTracker(item_type, item_id, source=source)
        return tracker.track(old, new)
    except Exception as err:
        print(f"{item_id}: failed to track history: {err}")
        return []


def track_deactivation(
    item_type: ItemType,
    item_id: str,
    old: dict | None,
    source: str = "reindex",
) -> list[dict]:
    """track an item going inactive, no new metadata available"""
    if not old:
        return []

    new = old.copy()
    new[ACTIVE_KEYS[item_type]] = False

    return track_changes(item_type, item_id, old, new, source=source)


class HistoryQuery:
    """read tracked changes back from ta_history"""

    DEFAULT_SIZE = 100

    def __init__(
        self,
        item_id: str | None = None,
        item_type: ItemType | None = None,
        channel_id: str | None = None,
        fields: list[str] | None = None,
        since: int | None = None,
        until: int | None = None,
    ):
        self.item_id = item_id
        self.item_type = item_type
        self.channel_id = channel_id
        self.fields = fields
        self.since = since
        self.until = until

    def build_query(self) -> dict:
        """build the filter part shared by all reads"""
        must_list: list[dict] = []
        if self.item_id:
            must_list.append({"term": {"item_id": {"value": self.item_id}}})
        if self.item_type:
            must_list.append(
                {"term": {"item_type": {"value": self.item_type}}}
            )
        if self.channel_id:
            must_list.append(
                {"term": {"channel_id": {"value": self.channel_id}}}
            )
        if self.fields:
            must_list.append({"terms": {"field": self.fields}})

        # the explicit format is required: es reads a bare numeric on a
        # date field as epoch *millis* regardless of the field's own
        # epoch_second format, so an int cutoff silently matches nothing
        # rather than erroring. Declaring it here keeps the range correct
        # whether an int or a string arrives, which str()-ing the values
        # would not. Same fix as DownscaleInteract's last_heartbeat range.
        time_range: dict = {}
        if self.since:
            time_range["gte"] = self.since
        if self.until:
            time_range["lte"] = self.until
        if time_range:
            time_range["format"] = "epoch_second"
            must_list.append({"range": {"timestamp": time_range}})

        if not must_list:
            return {"match_all": {}}

        return {"bool": {"must": must_list}}

    def get_changes(
        self, size: int | None = None, order: str = "desc"
    ) -> list[dict]:
        """get matching changes, newest first by default"""
        data = {
            "size": size or self.DEFAULT_SIZE,
            "query": self.build_query(),
            "sort": [
                {"timestamp": {"order": order}},
                {"field": {"order": "asc"}},
            ],
        }
        response, _ = ElasticWrap(f"{INDEX_NAME}/_search").get(data=data)
        hits = response.get("hits", {}).get("hits", [])

        return [decode_change(i["_source"]) for i in hits]

    def get_all_changes(self) -> list[dict]:
        """
        paginate through all matching changes, oldest first. Loads
        everything into memory, so filter to an item or a time range -
        the index runs to millions of documents on a large library.
        """
        data = {
            "query": self.build_query(),
            "sort": [{"timestamp": {"order": "asc"}}],
        }
        all_results = IndexPaginate(INDEX_NAME, data).get_results()

        return [decode_change(i) for i in all_results]

    def get_field_series(self, field: str) -> list[dict]:
        """
        get a numeric series for a single field, oldest first, e.g. to
        plot view_count over time
        """
        data = {
            "size": 10000,
            "query": {
                "bool": {
                    "must": [
                        self.build_query(),
                        {"term": {"field": {"value": field}}},
                        {"exists": {"field": "new_num"}},
                    ]
                }
            },
            "sort": [{"timestamp": {"order": "asc"}}],
            "_source": ["timestamp", "old_num", "new_num", "delta"],
        }
        response, _ = ElasticWrap(f"{INDEX_NAME}/_search").get(data=data)
        hits = response.get("hits", {}).get("hits", [])

        return [i["_source"] for i in hits]

    def get_tracked_fields(self) -> dict[str, int]:
        """get which fields have recorded changes, with their count"""
        data = {
            "size": 0,
            "query": self.build_query(),
            "aggs": {"fields": {"terms": {"field": "field", "size": 100}}},
        }
        response, _ = ElasticWrap(f"{INDEX_NAME}/_search").get(data=data)
        buckets = response.get("aggregations", {}).get("fields", {})

        return {i["key"]: i["doc_count"] for i in buckets.get("buckets", [])}

    def get_refresh_events(self, size: int | None = None) -> list[dict]:
        """
        group changes by refresh, newest refresh first. Groups are built
        from one `size` limited page, so the oldest event returned can be
        partial - raise `size` if a complete tail matters.
        """
        changes = self.get_changes(size=size, order="desc")
        events: dict[str, dict] = {}
        for change in changes:
            refresh_id = change["refresh_id"]
            event = events.setdefault(
                refresh_id,
                {
                    "refresh_id": refresh_id,
                    "item_id": change["item_id"],
                    "item_type": change["item_type"],
                    "timestamp": change["timestamp"],
                    "source": change.get("source"),
                    "changes": [],
                },
            )
            event["changes"].append(change)

        return list(events.values())

    def delete(self) -> None:
        """delete all matching history, e.g. when an item gets removed"""
        data = {"query": self.build_query()}
        path = f"{INDEX_NAME}/_delete_by_query?refresh=true"
        response, status_code = ElasticWrap(path).post(data)
        if status_code not in [200, 201]:
            print(f"failed to delete history: {response}")
