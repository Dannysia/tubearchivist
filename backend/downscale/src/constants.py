# set only once an accepted job has rewritten the file
DOWNSCALED_FIELD = "downscale.new_height"


DOWNSCALE_LADDER = [2160, 1440, 1080, 720, 480, 360, 240]


QUEUE_DOC_SOURCE_FIELDS = [
    "youtube_id",
    "streams",
    "title",
    "channel",
    "vid_thumb_url",
    "media_url",
    "media_size",
]


def downscaled_filter() -> dict:
    return {"exists": {"field": DOWNSCALED_FIELD}}


SIZE_CHANGE_VALUES = [
    "larger",
    "smaller",
    "smaller_lt_2",
    "smaller_lt_5",
    "smaller_lt_10",
    "smaller_gt_2",
    "smaller_gt_5",
    "smaller_gt_10",
    "smaller_gt_20",
    "smaller_gt_30",
    "smaller_gt_50",
]

SAVED_BUCKET_EDGES = [0, 5, 10, 20, 30, 50]
SIZE_CHANGE_EDGES = [0, 2, 5, 10, 20, 30, 50]


QUEUE_SIZE_FIELDS = ("original_size", "new_size")
VIDEO_SIZE_FIELDS = ("downscale.original_size", "downscale.new_size")


def _measurable_guard(fields: tuple[str, str] = QUEUE_SIZE_FIELDS) -> str:
    original, new = fields
    return (
        f"doc['{new}'].size() > 0 && doc['{original}'].size() > 0 "
        f"&& doc['{new}'].value > 0 && doc['{original}'].value > 0 "
        f"&& doc['{new}'].value != doc['{original}'].value"
    )


def size_change_clause(value: str) -> dict:
    guard = _measurable_guard()

    if value in ("smaller", "larger"):
        operator = "<" if value == "smaller" else ">"
        return {
            "script": {
                "script": {
                    "source": (
                        f"{guard} && doc['new_size'].value {operator} "
                        "doc['original_size'].value"
                    )
                }
            }
        }

    _, direction, threshold = value.split("_")
    operator = "<=" if direction == "gt" else ">"
    bounds = (
        f"doc['new_size'].value {operator} "
        "doc['original_size'].value * params.factor"
    )

    if direction == "lt":
        bounds += " && doc['new_size'].value < doc['original_size'].value"

    return {
        "script": {
            "script": {
                "source": f"{guard} && {bounds}",
                "params": {"factor": 1 - int(threshold) / 100},
            }
        }
    }


# sentinel for documents failing _measurable_guard, below every bucket
_UNMEASURABLE_SENTINEL = -10_000_000
LARGEST_GROWTH = -1_000_000


def saved_percent_agg(
    fields: tuple[str, str] = QUEUE_SIZE_FIELDS,
    edges: list[int] = SAVED_BUCKET_EDGES,
) -> dict:
    original, new = fields
    ranges: list[dict] = [{"key": "larger", "from": LARGEST_GROWTH, "to": 0}]
    for position, edge in enumerate(edges):
        entry: dict = {"key": str(edge), "from": edge}
        if position + 1 < len(edges):
            entry["to"] = edges[position + 1]
        ranges.append(entry)

    return {
        "range": {
            "script": {
                "source": (
                    f"if (!({_measurable_guard(fields)})) "
                    f"return {_UNMEASURABLE_SENTINEL};"
                    f"return (double)(doc['{original}'].value "
                    f"- doc['{new}'].value) "
                    f"/ doc['{original}'].value * 100;"
                )
            },
            "ranges": ranges,
        }
    }


def parse_saved_bands(agg: dict, total: int) -> dict:
    counts = {
        bucket["key"]: bucket["doc_count"] for bucket in agg.get("buckets", [])
    }
    bands = []
    for position, edge in enumerate(SAVED_BUCKET_EDGES):
        upper = (
            SAVED_BUCKET_EDGES[position + 1]
            if position + 1 < len(SAVED_BUCKET_EDGES)
            else None
        )
        bands.append(
            {
                "from": edge,
                "to": upper,
                "doc_count": counts.get(str(edge), 0),
            }
        )

    bands.reverse()
    grew = counts.get("larger", 0)
    accounted = sum(band["doc_count"] for band in bands) + grew

    return {
        "bands": bands,
        "grew": grew,
        "unknown": max(total - accounted, 0),
    }


TRANSITION_LIMIT = 5


def transition_agg(limit: int = TRANSITION_LIMIT) -> dict:
    return {
        "multi_terms": {
            "size": limit,
            "terms": [
                {"field": "downscale.original_height"},
                {"field": "downscale.new_height"},
            ],
            "order": {"_count": "desc"},
        }
    }


def parse_transitions(agg: dict) -> dict:
    """multi_terms keys arrive as an [original, new] list"""
    buckets = agg.get("buckets", [])

    return {
        "transitions": [
            {
                "original_height": int(bucket["key"][0]),
                "new_height": int(bucket["key"][1]),
                "doc_count": bucket["doc_count"],
            }
            for bucket in buckets
        ],
        "other_count": agg.get("sum_other_doc_count", 0),
    }
