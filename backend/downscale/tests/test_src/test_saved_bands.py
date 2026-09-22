"""
tests for the savings band payload behind the dashboard panel.

The bands are the same ones the queue's size filter rungs are summed
from, so these also pin the contract that keeps the two reporting in the
same categories.
"""

from downscale.src.constants import (
    QUEUE_SIZE_FIELDS,
    SAVED_BUCKET_EDGES,
    VIDEO_SIZE_FIELDS,
    parse_saved_bands,
    saved_percent_agg,
)


def _agg(**counts):
    """a range agg response with the given per band doc counts"""
    buckets = [{"key": "larger", "doc_count": counts.get("larger", 0)}]
    buckets += [
        {"key": str(edge), "doc_count": counts.get(str(edge), 0)}
        for edge in SAVED_BUCKET_EDGES
    ]
    return {"buckets": buckets}


def test_video_agg_reads_the_downscale_subfields():
    """
    a video doc carries the sizes an accepted job wrote under downscale,
    not at the top level like a queue doc - reading the queue's field
    names off a video would match nothing and report an empty panel
    """
    source = saved_percent_agg(VIDEO_SIZE_FIELDS)["range"]["script"]["source"]

    assert "doc['downscale.new_size']" in source
    assert "doc['downscale.original_size']" in source
    assert "doc['new_size']" not in source


def test_queue_fields_stay_the_default():
    """the size filter calls this with no argument and must not move"""
    source = saved_percent_agg()["range"]["script"]["source"]

    assert (
        source
        == saved_percent_agg(QUEUE_SIZE_FIELDS)["range"]["script"]["source"]
    )
    assert "downscale." not in source


def test_bands_run_biggest_saving_first():
    """the panel leads with the best result, like the transition panel"""
    parsed = parse_saved_bands(_agg(), total=0)
    edges = [band["from"] for band in parsed["bands"]]

    assert edges == sorted(SAVED_BUCKET_EDGES, reverse=True)
    assert parsed["bands"][0]["to"] is None
    assert parsed["bands"][-1]["from"] == 0


def test_counts_land_in_their_own_band():
    parsed = parse_saved_bands(
        _agg(**{"0": 3, "5": 4, "10": 5, "20": 6, "30": 7, "50": 8}), total=33
    )
    by_edge = {band["from"]: band["doc_count"] for band in parsed["bands"]}

    assert by_edge == {0: 3, 5: 4, 10: 5, 20: 6, 30: 7, 50: 8}
    assert parsed["unknown"] == 0


def test_grew_is_reported_separately_from_every_band():
    """
    a video that came out larger is not a saving of any size, so it must
    not be folded into the 0-5% band
    """
    parsed = parse_saved_bands(_agg(larger=9, **{"0": 1}), total=10)

    assert parsed["grew"] == 9
    assert {band["from"]: band["doc_count"] for band in parsed["bands"]}[
        0
    ] == 1


def test_rows_reconcile_with_the_caller_total():
    """
    the shortfall is reported rather than dropped, so the panel adds up
    to the downscaled total - a video whose original_size was never
    indexed fails the guard and lands in no band
    """
    parsed = parse_saved_bands(_agg(**{"50": 4}), total=7)

    counted = (
        sum(band["doc_count"] for band in parsed["bands"])
        + parsed["grew"]
        + parsed["unknown"]
    )
    assert parsed["unknown"] == 3
    assert counted == 7


def test_total_below_the_bands_never_goes_negative():
    """
    the agg and the total come from the same response, but clamp rather
    than render a negative row if they ever disagree
    """
    parsed = parse_saved_bands(_agg(**{"50": 4}), total=0)

    assert parsed["unknown"] == 0


def test_missing_buckets_read_as_zero():
    """ES omits nothing here, but an empty archive returns no buckets"""
    parsed = parse_saved_bands({}, total=0)

    assert [band["doc_count"] for band in parsed["bands"]] == [0] * len(
        SAVED_BUCKET_EDGES
    )
    assert parsed["grew"] == 0
