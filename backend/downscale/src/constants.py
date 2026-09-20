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
