"""test elastic index setup"""

# pylint: disable=protected-access,redefined-outer-name

import pytest
from appsettings.src.index_setup import ElasticIndex, MappingAction
from deepdiff import DeepDiff


@pytest.fixture
def elastic_index():
    """build index without connecting to Elasticsearch"""
    return object.__new__(ElasticIndex)


@pytest.fixture
def mapping_diff():
    """build tree diff from current and expected mappings"""

    def build(current, expected):
        return DeepDiff(
            current,
            expected,
            ignore_order=True,
            report_repetition=True,
            view="tree",
        )

    return build


@pytest.mark.parametrize(
    "current,expected,expected_action",
    [
        pytest.param({}, {}, MappingAction.NOOP, id="no-change"),
        pytest.param(
            {},
            {"title": {"type": "text"}},
            MappingAction.PUT_MAPPING,
            id="field-added",
        ),
        pytest.param(
            {"title": {"type": "keyword"}},
            {"title": {"type": "text"}},
            MappingAction.REINDEX,
            id="field-type-changed",
        ),
        pytest.param(
            {"title": {"type": "text", "analyzer": "standard"}},
            {"title": {"type": "text", "analyzer": "english"}},
            MappingAction.REINDEX,
            id="analyzer-changed",
        ),
    ],
)
def test_classify_mapping_diff(
    elastic_index, mapping_diff, current, expected, expected_action
):
    """classify mapping changes"""
    diff = mapping_diff(current, expected)

    assert elastic_index._classify_mapping_diff(diff) == expected_action


@pytest.mark.parametrize(
    "title_type,expected_action",
    [
        pytest.param("text", MappingAction.NOOP, id="deferred"),
        pytest.param("keyword", MappingAction.REINDEX, id="during-reindex"),
    ],
)
def test_removed_field_cleanup(
    elastic_index, mapping_diff, title_type, expected_action
):
    """keep removed fields until a reindex is needed"""
    current = {
        "title": {"type": title_type},
        "obsolete": {"type": "keyword"},
    }
    expected = {"title": {"type": "text"}}
    diff = mapping_diff(current, expected)

    assert elastic_index._classify_mapping_diff(diff) == expected_action
    assert elastic_index._get_fields_to_delete(diff) == {"obsolete"}
