"""test the query building behind the log page"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from common.views import LogView


def tasks_agg(query: dict) -> dict:
    built = LogView._build_task_aggs(query)
    return built["all"]["aggs"]["in_source"]["aggs"]["tasks"]["multi_terms"]


class TestBuildTaskAggs:
    def test_is_global_so_the_active_filters_do_not_narrow_it(self):
        built = LogView._build_task_aggs({"source": "notification"})
        assert built["all"]["global"] == {}

    def test_scopes_to_the_source(self):
        built = LogView._build_task_aggs({"source": "notification"})
        assert built["all"]["aggs"]["in_source"]["filter"] == {
            "term": {"source": {"value": "notification"}}
        }

    def test_spans_every_source_when_none_is_given(self):
        built = LogView._build_task_aggs({})
        assert built["all"]["aggs"]["in_source"]["filter"] == {"match_all": {}}

    def test_ignores_the_other_filters(self):
        query = {"source": "notification", "level": "error", "q": "boom"}
        assert tasks_agg(query) == tasks_agg({"source": "notification"})

    def test_a_task_without_a_title_still_buckets(self):
        terms = tasks_agg({"source": "notification"})["terms"]
        title = [i for i in terms if i["field"] == "task_title"][0]
        assert title["missing"] == ""


class TestParseTaskAggs:
    def test_reads_name_and_title_out_of_the_buckets(self):
        response = {
            "aggregations": {
                "all": {
                    "in_source": {
                        "tasks": {
                            "buckets": [
                                {
                                    "key": ["download_pending", "Downloading"],
                                    "doc_count": 3,
                                }
                            ]
                        }
                    }
                }
            }
        }
        assert LogView._parse_task_aggs(response) == [
            {"task_name": "download_pending", "task_title": "Downloading"}
        ]

    def test_an_empty_title_survives_for_the_frontend_to_fall_back_on(self):
        response = {
            "aggregations": {
                "all": {
                    "in_source": {
                        "tasks": {
                            "buckets": [
                                {"key": ["ghost_task", ""], "doc_count": 1}
                            ]
                        }
                    }
                }
            }
        }
        assert LogView._parse_task_aggs(response) == [
            {"task_name": "ghost_task", "task_title": ""}
        ]

    def test_no_aggregations_at_all_is_not_an_error(self):
        assert LogView._parse_task_aggs({}) == []
