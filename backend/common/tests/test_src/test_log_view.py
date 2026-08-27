"""test the query building behind the log page

The task filter is the fiddly part: it has to list every task in the
log rather than every task on the visible page, and it has to keep
listing them once one is picked.
"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from common.views import LogView


def tasks_agg(query: dict) -> dict:
    """the multi_terms body, dug out of the nesting"""
    built = LogView._build_task_aggs(query)
    return built["all"]["aggs"]["in_source"]["aggs"]["tasks"]["multi_terms"]


class TestBuildTaskAggs:
    """_build_task_aggs"""

    def test_is_global_so_the_active_filters_do_not_narrow_it(self):
        # without the global wrapper the dropdown would collapse to the
        # one task already picked, leaving no way back to the others
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
        # multi_terms drops a document missing any of its fields, so a
        # task with no TASK_CONFIG entry would have rows in the log that
        # the filter could not select
        terms = tasks_agg({"source": "notification"})["terms"]
        title = [i for i in terms if i["field"] == "task_title"][0]
        assert title["missing"] == ""


class TestParseTaskAggs:
    """_parse_task_aggs"""

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
