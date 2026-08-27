"""test the log writer

the never-raises contract is most of this: writing a log entry runs from
celery callbacks, where an exception is attributed to the task that just
finished and reads as that task having failed.
"""

import pytest
from common.src import log


class FakeWrap:
    """stands in for ElasticWrap, recording what it was asked to do"""

    calls: list = []

    def __init__(self, path):
        self.path = path

    def post(self, data=False, ndjson=False):
        FakeWrap.calls.append((self.path, data))
        return {"result": "created", "deleted": 2}, 201


@pytest.fixture(autouse=True)
def reset_calls():
    FakeWrap.calls = []


@pytest.fixture
def fake_es(monkeypatch):
    monkeypatch.setattr(log, "ElasticWrap", FakeWrap)
    return FakeWrap


class TestWriteLog:
    """write_log"""

    def test_writes_to_the_log_index(self, fake_es):
        log.write_log("notification", "info", "all done")
        path, data = fake_es.calls[0]
        assert path == "ta_log/_doc"
        assert data["source"] == "notification"
        assert data["level"] == "info"
        assert data["message"] == "all done"
        assert isinstance(data["timestamp"], int)

    def test_optional_fields_are_dropped_when_unset(self, fake_es):
        log.write_log("notification", "info", "all done")
        _, data = fake_es.calls[0]
        for key in ("event", "task_id", "task_name", "task_title", "group"):
            assert key not in data

    def test_optional_fields_are_kept_when_given(self, fake_es):
        log.write_log(
            "notification",
            "error",
            "Task failed: boom",
            event="failed",
            task_id="abc-123",
            task_name="download_pending",
            task_title="Downloading",
            group="download:run",
        )
        _, data = fake_es.calls[0]
        assert data["event"] == "failed"
        assert data["task_id"] == "abc-123"
        assert data["group"] == "download:run"

    def test_never_raises_on_a_broken_es(self, monkeypatch):
        def explode(_path):
            raise ConnectionError("no es here")

        monkeypatch.setattr(log, "ElasticWrap", explode)
        # the point of the whole module: this must return, not raise
        log.write_log("notification", "info", "all done")

    def test_never_raises_on_a_rejected_write(self, monkeypatch):
        class Rejecting(FakeWrap):
            def post(self, data=False, ndjson=False):
                return {"error": "mapper_parsing_exception"}, 400

        monkeypatch.setattr(log, "ElasticWrap", Rejecting)
        log.write_log("notification", "info", "all done")


class TestPruneLogs:
    """prune_logs"""

    def test_deletes_older_than_the_window(self, fake_es):
        deleted = log.prune_logs(7)
        path, data = fake_es.calls[0]
        assert path == "ta_log/_delete_by_query"
        assert deleted == 2

        cutoff = data["query"]["range"]["timestamp"]["lt"]
        expected = log.now_epoch() - 7 * log.DAY_SECONDS
        assert abs(cutoff - expected) < 5

    def test_declares_the_epoch_format(self, fake_es):
        # without this es reads the bare int as epoch millis and the
        # range silently matches nothing rather than erroring
        log.prune_logs(7)
        _, data = fake_es.calls[0]
        assert data["query"]["range"]["timestamp"]["format"] == "epoch_second"

    def test_falls_back_when_no_window_is_given(self, fake_es):
        log.prune_logs(None)
        _, data = fake_es.calls[0]
        cutoff = data["query"]["range"]["timestamp"]["lt"]
        expected = (
            log.now_epoch() - log.FALLBACK_RETENTION_DAYS * log.DAY_SECONDS
        )
        assert abs(cutoff - expected) < 5


class TestClearLogs:
    """clear_logs"""

    def test_clears_everything_by_default(self, fake_es):
        assert log.clear_logs() == 2
        _, data = fake_es.calls[0]
        assert data["query"] == {"match_all": {}}

    def test_refreshes_so_the_page_can_read_back_immediately(self, fake_es):
        # the logs page re-reads the moment the delete returns, and
        # without this the cleared entries are still there
        log.clear_logs()
        path, _ = fake_es.calls[0]
        assert path == "ta_log/_delete_by_query?refresh=true"

    def test_prune_does_not_pay_for_a_refresh(self, fake_es):
        # nothing reads straight after the scheduled prune, so it does
        # not need to force one
        log.prune_logs(7)
        path, _ = fake_es.calls[0]
        assert path == "ta_log/_delete_by_query"

    def test_clears_one_source_only(self, fake_es):
        log.clear_logs("notification")
        _, data = fake_es.calls[0]
        assert data["query"] == {"term": {"source": {"value": "notification"}}}
