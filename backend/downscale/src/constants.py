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

# Boundaries of the disjoint savings buckets the aggs endpoint counts.
# The dropdown's rungs overlap (>5% contains >10%), so they cannot be
# aggregated directly - the frontend sums these instead. Kept here
# beside the rungs so a new rung and its bucket edge stay together.
SAVED_BUCKET_EDGES = [0, 5, 10, 20, 30, 50]


def _finished_guard() -> str:
    """
    painless condition for "this job produced a result that changed the
    size", which every rung and every band is gated on.

    Both sizes have to be present and positive: new_size is 0 until
    _finish_success() writes it, so without this a queued job reads as a
    100% saving and lands in the best rung of the dropdown; and
    original_size comes off the video doc and can be 0 where media_size
    was never indexed, which would throw on the division the bands do.

    An encode that came out byte for byte the same size is excluded too.
    It is neither smaller nor larger, so it matches no rung, and without
    this it would still land in the 0-5% band and be counted by a rung
    that cannot return it.
    """
    return (
        "doc['new_size'].size() > 0 && doc['original_size'].size() > 0 "
        "&& doc['new_size'].value > 0 && doc['original_size'].value > 0 "
        "&& doc['new_size'].value != doc['original_size'].value"
    )


def size_change_clause(value: str) -> dict:
    """
    es clause for one size filter rung.

    The plain smaller/larger pair compares the two sizes directly rather
    than going through the percentage, so a job that saved a fraction of
    a percent still counts as smaller.
    """
    guard = _finished_guard()

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


# A range agg has to put every document somewhere or nowhere, and an
# unfinished job belongs nowhere - so the script hands those a sentinel
# far below any real percentage and no bucket reaches down to it. The
# "larger" bucket is therefore bounded rather than open ended: left
# open, it would swallow the sentinel and report every queued job as
# one that grew. LARGEST_GROWTH is the floor for real growth - a job
# would have to balloon to ten thousand times its original size to fall
# past it, which no encode does.
_UNFINISHED_SENTINEL = -10_000_000
LARGEST_GROWTH = -1_000_000


def saved_percent_agg() -> dict:
    """
    es agg counting finished jobs per savings band, so the size filter
    dropdown can show how many jobs each rung would match.

    Buckets are disjoint because a range agg cannot express the
    dropdown's overlapping rungs (>5% contains >10%); the frontend sums
    them back up. Jobs that never finished are counted nowhere, matching
    what the filter itself does with them.
    """
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
                    f"if (!({_finished_guard()})) "
                    f"return {_UNFINISHED_SENTINEL};"
                    "return (double)(doc['original_size'].value "
                    "- doc['new_size'].value) "
                    "/ doc['original_size'].value * 100;"
                )
            },
            "ranges": ranges,
        }
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
