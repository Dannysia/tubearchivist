from downscale.src.constants import (
    TRANSITION_LIMIT,
    parse_transitions,
    transition_agg,
)


def a_response(buckets=None, other=0):
    return {"buckets": buckets or [], "sum_other_doc_count": other}


class TestTransitionAgg:
    def test_counts_the_pair_not_each_height(self):
        terms = transition_agg()["multi_terms"]["terms"]

        assert terms == [
            {"field": "downscale.original_height"},
            {"field": "downscale.new_height"},
        ]

    def test_biggest_first(self):
        assert transition_agg()["multi_terms"]["order"] == {"_count": "desc"}

    def test_defaults_to_the_panel_limit(self):
        assert transition_agg()["multi_terms"]["size"] == TRANSITION_LIMIT
        assert TRANSITION_LIMIT == 5

    def test_limit_is_overridable(self):
        assert transition_agg(limit=3)["multi_terms"]["size"] == 3


class TestParseTransitions:
    def test_splits_the_multi_terms_key_into_both_heights(self):
        parsed = parse_transitions(
            a_response([{"key": [2160, 1080], "doc_count": 12}])
        )

        assert parsed["transitions"] == [
            {"original_height": 2160, "new_height": 1080, "doc_count": 12}
        ]

    def test_keeps_the_order_es_returned(self):
        parsed = parse_transitions(
            a_response(
                [
                    {"key": [2160, 1080], "doc_count": 12},
                    {"key": [1440, 1080], "doc_count": 5},
                    {"key": [1080, 480], "doc_count": 2},
                ]
            )
        )
        counts = [i["doc_count"] for i in parsed["transitions"]]

        assert counts == [12, 5, 2]

    def test_reports_what_fell_outside_the_top_n(self):
        parsed = parse_transitions(
            a_response([{"key": [2160, 1080], "doc_count": 12}], other=7)
        )

        assert parsed["other_count"] == 7

    def test_handles_a_string_key(self):
        parsed = parse_transitions(
            a_response([{"key": ["2160", "1080"], "doc_count": 1}])
        )

        assert parsed["transitions"][0]["original_height"] == 2160
        assert parsed["transitions"][0]["new_height"] == 1080

    def test_nothing_downscaled(self):
        parsed = parse_transitions(a_response())

        assert parsed == {"transitions": [], "other_count": 0}

    def test_tolerates_a_missing_other_count(self):
        parsed = parse_transitions({"buckets": []})

        assert parsed["other_count"] == 0
