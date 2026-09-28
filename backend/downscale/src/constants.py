# set only once an accepted job has rewritten the file.
# downscale.encoder is the tempting alternative and the wrong one: it
# can be null on a job that finished without reporting an encoder.
DOWNSCALED_FIELD = "downscale.new_height"


# target heights offered for a downscale, highest first. The frontend
# dropdowns keep their own copy - nothing ships this list to them.
DOWNSCALE_LADDER = [2160, 1440, 1080, 720, 480, 360, 240]


# exactly the fields build_queued_doc reads off a video document: a
# fetch missing one queues a job with a null title or no media_url.
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


# the rungs the size filter offers, in dropdown order.
# "smaller"/"larger" predate the rungs and keep their old meaning, so an
# existing ?size_change=smaller link still resolves. smaller_lt_N saved
# less than N%, smaller_gt_N saved N% or more; the boundary belongs to
# gt so lt_5 and gt_5 partition "smaller" exactly.
SIZE_CHANGE_VALUES = [
    "larger",
    "smaller",
    "smaller_lt_5",
    "smaller_lt_10",
    "smaller_gt_5",
    "smaller_gt_10",
    "smaller_gt_20",
    "smaller_gt_30",
    "smaller_gt_50",
]

# boundaries of the disjoint savings bands: the rungs above overlap
# (>5% contains >10%) and a range agg cannot express that, so the
# filter sums these instead.
SAVED_BUCKET_EDGES = [0, 5, 10, 20, 30, 50]


QUEUE_SIZE_FIELDS = ("original_size", "new_size")
VIDEO_SIZE_FIELDS = ("downscale.original_size", "downscale.new_size")


def _measurable_guard(fields: tuple[str, str] = QUEUE_SIZE_FIELDS) -> str:
    """
    new_size is 0 on a queued job, which would otherwise read as a 100%
    saving; original_size is 0 where media_size was never indexed,
    which would throw on the division the bands do; and a byte for byte
    identical encode is neither smaller nor larger, so it belongs in no
    band at all.
    """
    original, new = fields
    return (
        f"doc['{new}'].size() > 0 && doc['{original}'].size() > 0 "
        f"&& doc['{new}'].value > 0 && doc['{original}'].value > 0 "
        f"&& doc['{new}'].value != doc['{original}'].value"
    )


def size_change_clause(value: str) -> dict:
    """
    smaller/larger compare the two sizes directly rather than the
    percentage, so a job that saved a fraction of a percent still
    counts as smaller.
    """
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
    # saved% >= threshold as a multiplication by (1 - t/100): no
    # division in the hot path, no second divide-by-zero to guard
    operator = "<=" if direction == "gt" else ">"
    bounds = (
        f"doc['new_size'].value {operator} "
        "doc['original_size'].value * params.factor"
    )

    if direction == "lt":
        # the threshold only closes the band's lower edge: without the
        # upper one every job that *grew* also sits above original *
        # factor, so "got smaller (<5%)" would return jobs that had
        # doubled in size
        bounds += " && doc['new_size'].value < doc['original_size'].value"

    return {
        "script": {
            "script": {
                "source": f"{guard} && {bounds}",
                "params": {"factor": 1 - int(threshold) / 100},
            }
        }
    }


# a range agg puts every document somewhere or nowhere, so documents
# failing _measurable_guard get a sentinel far below any real
# percentage that no bucket reaches down to. The "larger" bucket is
# therefore bounded rather than open ended - left open it would swallow
# the sentinel and report every unmeasurable document as one that grew.
# LARGEST_GROWTH is the floor for real growth: an encode would have to
# balloon ten thousand fold to fall past it.
_UNMEASURABLE_SENTINEL = -10_000_000
LARGEST_GROWTH = -1_000_000


def saved_percent_agg(
    fields: tuple[str, str] = QUEUE_SIZE_FIELDS,
) -> dict:
    """
    anything failing the guard is counted in no bucket, matching what
    the filter does with it; callers that need their rows to reconcile
    with a total read the shortfall off parse_saved_bands.
    """
    original, new = fields
    ranges: list[dict] = [{"key": "larger", "from": LARGEST_GROWTH, "to": 0}]
    for position, edge in enumerate(SAVED_BUCKET_EDGES):
        entry: dict = {"key": str(edge), "from": edge}
        if position + 1 < len(SAVED_BUCKET_EDGES):
            entry["to"] = SAVED_BUCKET_EDGES[position + 1]
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
    """
    bands come back ascending and are reversed here, biggest saving
    first. unknown is the shortfall against the caller's own total, not
    a bucket ES returns: a video whose media_size was never indexed, or
    whose encode came out byte identical, fails the guard and would
    otherwise go missing from the panel's total.
    """
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


# a top 5 was asked for; the tail is reported as a single remainder
# count rather than dropped, so the panel still reconciles with the
# downscaled total.
TRANSITION_LIMIT = 5


def transition_agg(limit: int = TRANSITION_LIMIT) -> dict:
    """
    multi_terms rather than two nested terms aggs: the pair is the
    thing being counted, and a nested shape would need flattening back
    into pairs on the way out.
    """
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
    """
    multi_terms keys arrive as an [original, new] list.
    sum_other_doc_count is what ES did not return - taking it from the
    response rather than subtracting from a separately queried total
    keeps the remainder exact under concurrent writes.
    """
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


def empty_transitions() -> dict:
    return {"transitions": [], "other_count": 0}
