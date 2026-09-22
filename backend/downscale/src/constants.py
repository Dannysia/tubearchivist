"""downscale constants"""

# A video document only carries downscale.new_height once an accepted job
# has rewritten the file - see DownscaleReview. downscale.encoder is the
# tempting alternative and is the wrong one: it comes from
# job.get("encoder") and can be null on a job that finished without
# reporting one.
#
# Every place that asks "has this video been downscaled" must build its
# clause from here. The video list filter, the channel about panel and
# the dashboard savings all report on this same set, and when they were
# three separate literals nothing stopped one of them drifting and
# silently reporting on a different set than the other two.
DOWNSCALED_FIELD = "downscale.new_height"


# The target heights offered for a downscale, highest first. The
# downscale request choices and the resolution breakdown on the
# dashboard and channel about panels both build from this, so the
# categories the stats report in are the same ones a downscale can
# actually target. The two batch downscale dropdowns keep their own copy
# of the list - nothing ships this one to the frontend.
DOWNSCALE_LADDER = [2160, 1440, 1080, 720, 480, 360, 240]


# The video fields DownscaleInteract.build_queued_doc reads off a video
# document. Anything fetching videos in order to queue a downscale has
# to ask ES for exactly these - the channel batch view and the per
# channel auto downscale on download both do, and when the list was
# written out twice it was one edit away from one of them queueing jobs
# with a null title or a missing media_url.
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
    """es clause matching videos that have been downscaled"""
    return {"exists": {"field": DOWNSCALED_FIELD}}


# The savings rungs the queue's size filter offers, in the order the
# dropdown shows them. "smaller"/"larger" predate the rungs and keep
# their old meaning, so an existing ?size_change=smaller link still
# resolves.
#
# A rung is "smaller_lt_N" (saved less than N%) or "smaller_gt_N" (saved
# N% or more). The boundary belongs to the gt rung so that lt_5 and gt_5
# partition "smaller" exactly, leaving no job that neither matches.
#
# The list serializer validates against this list and size_change_clause
# translates it, so those two cannot drift. The dropdown keeps its own
# copy of the rungs and owns their labels - nothing ships this list to
# the frontend, the same as DOWNSCALE_LADDER above. That duplication is
# survivable in the direction it can fail: a rung the frontend offers
# and this does not is rejected as an invalid choice, which is a 400
# naming the field, not a 500 with nothing in the log.
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

# Boundaries of the disjoint savings bands. The savings panels report
# them as they are; the size filter dropdown cannot, because its rungs
# overlap (>5% contains >10%) and a range agg has no way to express
# that - it sums these instead. Kept here beside the rungs so a new
# rung and its band edge stay together.
SAVED_BUCKET_EDGES = [0, 5, 10, 20, 30, 50]


# Where the two sizes live on each document the savings maths runs over.
# A queue doc carries them at the top level; a video doc carries the
# numbers an accepted job wrote under downscale.
QUEUE_SIZE_FIELDS = ("original_size", "new_size")
VIDEO_SIZE_FIELDS = ("downscale.original_size", "downscale.new_size")


def _measurable_guard(fields: tuple[str, str] = QUEUE_SIZE_FIELDS) -> str:
    """
    painless condition for "there is a real size change here to
    measure", which every rung and every band is gated on. Both sizes
    present, both positive, and the two different.

    Deliberately not named for jobs: this gates queue documents and
    video documents alike, and the reason a document fails it differs
    between them.

    On a queue doc, new_size is 0 until _finish_success() writes it, so
    without this a queued job reads as a 100% saving and lands in the
    best rung of the dropdown. On a video doc, original_size comes from
    the media_size indexed at download and can be 0 where that never
    happened, which would throw on the division the bands do.

    Either kind can also come out byte for byte the same size, which is
    neither smaller nor larger. That matches no rung, and without this
    it would still land in the 0-5% band and be counted by a rung that
    cannot return it.
    """
    original, new = fields
    return (
        f"doc['{new}'].size() > 0 && doc['{original}'].size() > 0 "
        f"&& doc['{new}'].value > 0 && doc['{original}'].value > 0 "
        f"&& doc['{new}'].value != doc['{original}'].value"
    )


def size_change_clause(value: str) -> dict:
    """
    es clause for one size filter rung.

    The plain smaller/larger pair compares the two sizes directly rather
    than going through the percentage, so a job that saved a fraction of
    a percent still counts as smaller.
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
    # saved% >= threshold  <=>  new_size <= original_size * (1 - t/100),
    # done as a multiplication so there is no division in the hot path
    # and no divide-by-zero to guard a second time
    operator = "<=" if direction == "gt" else ">"
    bounds = (
        f"doc['new_size'].value {operator} "
        "doc['original_size'].value * params.factor"
    )

    if direction == "lt":
        # "saved less than N%" is a band, not a half line, and the
        # threshold only closes its lower edge. Without the upper one
        # every job that *grew* also sits above original * factor, so
        # "got smaller (<5%)" returned jobs that had doubled in size -
        # and the reject-by-filter pass built on that rung would have
        # swept them up under a label saying they shrank.
        bounds += " && doc['new_size'].value < doc['original_size'].value"

    return {
        "script": {
            "script": {
                "source": f"{guard} && {bounds}",
                "params": {"factor": 1 - int(threshold) / 100},
            }
        }
    }


# A range agg has to put every document somewhere or nowhere, and one
# that fails _measurable_guard belongs nowhere - so the script hands
# those a sentinel far below any real percentage and no bucket reaches
# down to it. The "larger" bucket is therefore bounded rather than open
# ended: left open it would swallow the sentinel and report every
# unmeasurable document as one that grew, which on the queue means the
# entire queued backlog. LARGEST_GROWTH is the floor for real growth -
# an encode would have to balloon to ten thousand times its original
# size to fall past it, which none does.
_UNMEASURABLE_SENTINEL = -10_000_000
LARGEST_GROWTH = -1_000_000


def saved_percent_agg(
    fields: tuple[str, str] = QUEUE_SIZE_FIELDS,
) -> dict:
    """
    es agg counting documents per savings band.

    Three consumers, the same bands: the queue's size filter dropdown
    sums them into its rungs to show how many jobs each would match, and
    the savings panels on the dashboard and the channel about page
    report them as they are. Sharing the edges is what keeps the
    categories the stats report in the same ones the filter can actually
    select, the same reason DOWNSCALE_LADDER is shared between the
    request choices and the resolution breakdown.

    Buckets are disjoint because a range agg cannot express the
    dropdown's overlapping rungs (>5% contains >10%). Anything failing
    the guard is counted nowhere, matching what the filter does with it;
    callers that need their rows to reconcile with a total read the
    shortfall off parse_saved_bands.
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
    turn a saved_percent_agg response into the savings panel payload -
    the same one backs the dashboard and the channel about page: the
    bands biggest first, the count that grew instead, and whatever the
    bands could not account for.

    Bands come back ascending and are reversed here so the panel leads
    with the biggest saving, the way the transition panel leads with the
    most common pair.

    unknown is the shortfall against the caller's own total rather than
    a bucket ES returns. A downscaled video whose media_size was
    never indexed has an original_size of 0 and fails the guard, as does
    one whose encode came out byte identical - counting those as a row
    keeps the panel adding up to the downscaled total instead of quietly
    losing them, the same contract the transition panel's other_count
    holds to.
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


# How many original -> new height pairs the downscale count panels show.
# The user asked for a top 5; anything past it is reported as a single
# remainder count rather than dropped, so the panel still reconciles
# with the downscaled total the savings panel reports - the same reason
# the encoder savings breakdown folds its tail into OTHER_ENCODER.
TRANSITION_LIMIT = 5


def transition_agg(limit: int = TRANSITION_LIMIT) -> dict:
    """
    es agg counting videos per original -> new height pair, biggest
    first. Shared by the global stats page and the channel about panel
    so both report the same pairs in the same order - when the video
    list filter, the channel panel and the dashboard each built their
    own downscale clause they drifted, which is what DOWNSCALED_FIELD
    above exists to prevent.

    multi_terms rather than two nested terms aggs: the pair is the
    thing being counted, and a nested shape would need flattening back
    into pairs on the way out for no gain.
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
    turn a transition_agg response into the panel payload: the pairs
    themselves plus how many downscaled videos fell outside the top N.

    multi_terms keys arrive as a [original, new] list, and
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
    """transition payload for a channel with nothing downscaled"""
    return {"transitions": [], "other_count": 0}
