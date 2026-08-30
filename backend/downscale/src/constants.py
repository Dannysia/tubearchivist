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


def downscaled_filter() -> dict:
    """es clause matching videos that have been downscaled"""
    return {"exists": {"field": DOWNSCALED_FIELD}}
