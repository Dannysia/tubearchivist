"""
tests for the savings rungs behind the downscale queue's size filter.

The rungs, the clause they build and the bands the dropdown counts all
come out of downscale.src.constants, so they are exercised here rather
than through the view - _build_must_list only forwards to them.
"""

import pytest
from downscale.src.constants import (
    LARGEST_GROWTH,
    SAVED_BUCKET_EDGES,
    SIZE_CHANGE_VALUES,
    saved_percent_agg,
    size_change_clause,
)
from downscale.views import _build_must_list


def _source(value):
    return size_change_clause(value)["script"]["script"]["source"]


def _params(value):
    return size_change_clause(value)["script"]["script"].get("params", {})


def test_plain_smaller_and_larger_keep_their_old_meaning():
    """
    an existing ?size_change=smaller link has to keep resolving, and a
    direct size comparison - not a percentage - is what makes a job that
    saved a fraction of a percent still count as smaller
    """
    assert "doc['new_size'].value < doc['original_size'].value" in _source(
        "smaller"
    )
    assert "doc['new_size'].value > doc['original_size'].value" in _source(
        "larger"
    )
    assert _params("smaller") == {}


@pytest.mark.parametrize("value", SIZE_CHANGE_VALUES)
def test_every_rung_excludes_unfinished_jobs(value):
    """
    new_size stays 0 until _finish_success writes it, so without this
    guard every queued job would read as a 100% saving and land in the
    best rung of the dropdown
    """
    source = _source(value)

    assert "doc['new_size'].value > 0" in source
    assert "doc['original_size'].value > 0" in source


@pytest.mark.parametrize(
    "value, factor",
    [
        ("smaller_gt_5", 0.95),
        ("smaller_gt_10", 0.90),
        ("smaller_gt_20", 0.80),
        ("smaller_gt_30", 0.70),
        ("smaller_gt_50", 0.50),
        ("smaller_lt_5", 0.95),
        ("smaller_lt_10", 0.90),
    ],
)
def test_threshold_becomes_a_multiplier_on_the_original(value, factor):
    """
    saved% >= N is expressed as new_size <= original * (1 - N/100), so
    the threshold reaches ES as a bound rather than a division
    """
    assert _params(value) == {"factor": pytest.approx(factor)}
    assert "params.factor" in _source(value)


def test_lt_and_gt_at_the_same_threshold_are_complementary():
    """
    lt_5 and gt_5 must partition "smaller" exactly - a job saving
    precisely 5% has to land in one of them and not both, or a reject
    pass over lt_5 would silently leave jobs behind
    """
    assert "<=" in _source("smaller_gt_5")
    assert ">" in _source("smaller_lt_5")
    assert "<=" not in _source("smaller_lt_5")


def test_rungs_reach_the_query_builder():
    """the view forwards the rung rather than reimplementing it"""
    [clause] = _build_must_list({"size_change": "smaller_gt_20"})

    assert clause == size_change_clause("smaller_gt_20")


def test_every_rung_has_a_band_to_count_it():
    """
    each gt rung is summed from the bands at or above its threshold, so
    a rung whose threshold is not a band edge could not be counted
    """
    thresholds = [
        int(value.rsplit("_", 1)[1])
        for value in SIZE_CHANGE_VALUES
        if value.startswith("smaller_")
    ]

    assert set(thresholds) <= set(SAVED_BUCKET_EDGES)


def test_unfinished_jobs_fall_outside_every_band():
    """
    a range agg counts a document in whichever band contains its value,
    so the sentinel for an unfinished job has to sit below the lowest
    band - if "larger" were left open ended it would swallow the whole
    queued backlog and the dropdown would report it as jobs that grew
    """
    agg = saved_percent_agg()["range"]
    sentinel = int(agg["script"]["source"].split("return ")[1].split(";")[0])
    larger = next(r for r in agg["ranges"] if r["key"] == "larger")

    assert sentinel < LARGEST_GROWTH == larger["from"]
    assert all("from" in band for band in agg["ranges"])


def test_bands_are_contiguous_and_disjoint():
    """
    the frontend sums bands into the dropdown's overlapping rungs, so a
    gap would undercount a rung and an overlap would double count it
    """
    agg = saved_percent_agg()["range"]
    bands = agg["ranges"]

    for lower, upper in zip(bands, bands[1:]):
        assert lower["to"] == upper["from"]

    assert "to" not in bands[-1]


def _evaluate(value: str, original: int, new: int) -> bool:
    """
    decide whether a job with these two sizes matches a rung, by reading
    the generated painless rather than restating its logic - a test that
    reimplemented the comparison would agree with a wrong clause.
    """
    script = size_change_clause(value)["script"]["script"]
    expression = script["source"]
    for painless, python in (
        ("doc['new_size'].size() > 0", "True"),
        ("doc['original_size'].size() > 0", "True"),
        ("doc['new_size'].value", str(new)),
        ("doc['original_size'].value", str(original)),
        ("params.factor", str(script.get("params", {}).get("factor"))),
        ("&&", "and"),
        ("!=", "!="),
    ):
        expression = expression.replace(painless, python)

    return eval(expression)  # noqa: S307 - generated by the code under test


@pytest.mark.parametrize(
    "original, new, expected",
    [
        (
            1000,
            500,
            {
                "smaller",
                "smaller_gt_5",
                "smaller_gt_10",
                "smaller_gt_20",
                "smaller_gt_30",
                "smaller_gt_50",
            },
        ),
        (1000, 960, {"smaller", "smaller_lt_5", "smaller_lt_10"}),
        # exactly 10%: the boundary belongs to the gt rung, so lt_10
        # must not also claim it
        (1000, 900, {"smaller", "smaller_gt_5", "smaller_gt_10"}),
        # byte for byte identical: neither smaller nor larger, so no rung
        (1000, 1000, set()),
        # the regression - a job that grew must never answer a "smaller"
        # rung, however small the threshold
        (1000, 1020, {"larger"}),
        (1000, 2000, {"larger"}),
        # never finished, so no rung at all
        (1000, 0, set()),
    ],
)
def test_which_rungs_a_job_actually_matches(original, new, expected):
    matched = {
        value
        for value in SIZE_CHANGE_VALUES
        if _evaluate(value, original, new)
    }

    assert matched == expected


@pytest.mark.parametrize("threshold", [5, 10])
def test_lt_rung_is_bounded_on_both_sides(threshold):
    """
    "saved less than N%" is a band - closed below by the threshold and
    above by the job having shrunk at all
    """
    assert _evaluate(f"smaller_lt_{threshold}", 1000, 999)
    assert not _evaluate(f"smaller_lt_{threshold}", 1000, 1001)
