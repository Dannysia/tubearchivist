"""test downscale savings aggregation"""

# pylint: disable=protected-access

from stats.src.aggs import Downscale


def test_query_filters_on_new_height():
    """same downscaled marker as the channel panel and video filter"""
    assert Downscale.data["query"] == {
        "exists": {"field": "downscale.new_height"}
    }


def test_query_aggs():
    """sums the recorded sizes, split by encoder"""
    aggs = Downscale.data["aggs"]
    assert aggs["original_size"] == {
        "sum": {"field": "downscale.original_size"}
    }
    assert aggs["new_size"] == {"sum": {"field": "downscale.new_size"}}
    assert aggs["by_encoder"]["terms"]["field"] == "downscale.encoder"


def test_encoder_buckets_are_bounded():
    """the breakdown never grows past the display limit"""
    terms = Downscale.data["aggs"]["by_encoder"]["terms"]
    assert terms["size"] == Downscale.ENCODER_LIMIT
    assert terms["order"] == {"original_size": "desc"}


def test_build_totals():
    """savings and percent of the original"""
    agg = {"original_size": {"value": 1000.0}, "new_size": {"value": 250.0}}
    assert Downscale._build_totals(4, agg) == {
        "doc_count": 4,
        "original_size": 1000,
        "new_size": 250,
        "saved": 750,
        "saved_percent": 75.0,
    }


def test_build_totals_with_encoder():
    """encoder buckets carry their key"""
    agg = {"original_size": {"value": 200.0}, "new_size": {"value": 100.0}}
    result = Downscale._build_totals(1, agg, "nvenc_av1_10bit")
    assert result["encoder"] == "nvenc_av1_10bit"
    assert result["saved_percent"] == 50.0


def test_build_totals_nothing_downscaled():
    """no division by zero when nothing matched"""
    agg = {"original_size": {"value": 0}, "new_size": {"value": 0}}
    assert Downscale._build_totals(0, agg) == {
        "doc_count": 0,
        "original_size": 0,
        "new_size": 0,
        "saved": 0,
        "saved_percent": 0,
    }


def test_build_totals_grown():
    """an encode that came out bigger reports a negative saving"""
    agg = {"original_size": {"value": 100.0}, "new_size": {"value": 150.0}}
    result = Downscale._build_totals(1, agg)
    assert result["saved"] == -50
    assert result["saved_percent"] == -50.0


def build_encoder(doc_count, original_size, new_size, encoder="h265"):
    """build a parsed encoder entry"""
    return {
        "encoder": encoder,
        "doc_count": doc_count,
        "original_size": original_size,
        "new_size": new_size,
        "saved": original_size - new_size,
        "saved_percent": 0,
    }


def test_no_remainder_when_every_encoder_is_shown():
    """the shown encoders already account for the total"""
    total = {"doc_count": 3, "original_size": 300, "new_size": 100}
    shown = [
        build_encoder(2, 200, 60, "h265"),
        build_encoder(1, 100, 40, "h264"),
    ]
    assert Downscale._build_remainder(total, shown) is None


def test_remainder_folds_the_truncated_tail():
    """what the terms agg left out still reconciles with the total"""
    total = {"doc_count": 10, "original_size": 1000, "new_size": 400}
    shown = [build_encoder(7, 800, 300, "h265")]

    assert Downscale._build_remainder(total, shown) == {
        "encoder": Downscale.OTHER_ENCODER,
        "doc_count": 3,
        "original_size": 200,
        "new_size": 100,
        "saved": 100,
        "saved_percent": 50.0,
    }


def test_remainder_reconciles_with_the_total():
    """shown plus remainder is exactly the total, whatever was dropped"""
    total = {"doc_count": 9, "original_size": 900, "new_size": 250}
    shown = [
        build_encoder(4, 500, 100, "h265"),
        build_encoder(2, 200, 90, "h264"),
    ]
    remainder = Downscale._build_remainder(total, shown)
    entries = shown + [remainder]

    for key in ["doc_count", "original_size", "new_size"]:
        assert sum(i[key] for i in entries) == total[key]


def test_remainder_ignores_a_negative_count():
    """never emit an entry for a total that is already accounted for"""
    total = {"doc_count": 2, "original_size": 100, "new_size": 50}
    shown = [build_encoder(2, 100, 50, "h265")]
    assert Downscale._build_remainder(total, shown) is None
