from downscale.src.constants import (
    QUEUE_SIZE_FIELDS,
    SAVED_BUCKET_EDGES,
    VIDEO_SIZE_FIELDS,
    parse_saved_bands,
    saved_percent_agg,
)


def _agg(**counts):
    buckets = [{"key": "larger", "doc_count": counts.get("larger", 0)}]
    buckets += [
        {"key": str(edge), "doc_count": counts.get(str(edge), 0)}
        for edge in SAVED_BUCKET_EDGES
    ]
    return {"buckets": buckets}


def test_video_agg_reads_the_downscale_subfields():
    source = saved_percent_agg(VIDEO_SIZE_FIELDS)["range"]["script"]["source"]

    assert "doc['downscale.new_size']" in source
    assert "doc['downscale.original_size']" in source
    assert "doc['new_size']" not in source


def test_queue_fields_stay_the_default():
    source = saved_percent_agg()["range"]["script"]["source"]

    assert (
        source
        == saved_percent_agg(QUEUE_SIZE_FIELDS)["range"]["script"]["source"]
    )
    assert "downscale." not in source


def test_bands_run_biggest_saving_first():
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
    parsed = parse_saved_bands(_agg(larger=9, **{"0": 1}), total=10)

    assert parsed["grew"] == 9
    assert {band["from"]: band["doc_count"] for band in parsed["bands"]}[
        0
    ] == 1


def test_rows_reconcile_with_the_caller_total():
    parsed = parse_saved_bands(_agg(**{"50": 4}), total=7)

    counted = (
        sum(band["doc_count"] for band in parsed["bands"])
        + parsed["grew"]
        + parsed["unknown"]
    )
    assert parsed["unknown"] == 3
    assert counted == 7


def test_total_below_the_bands_never_goes_negative():
    parsed = parse_saved_bands(_agg(**{"50": 4}), total=0)

    assert parsed["unknown"] == 0


def test_missing_buckets_read_as_zero():
    parsed = parse_saved_bands({}, total=0)

    assert [band["doc_count"] for band in parsed["bands"]] == [0] * len(
        SAVED_BUCKET_EDGES
    )
    assert parsed["grew"] == 0
