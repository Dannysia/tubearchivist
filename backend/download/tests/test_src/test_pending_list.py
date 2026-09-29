"""tests for PendingList functions"""

from datetime import datetime, timezone

from download.src import queue
from download.src.queue import PendingIndex, PendingList


def test_returns_scientific_timestamp_if_present():
    video_data = {"timestamp": 1.5135732e9}
    result = PendingList._extract_published(video_data)
    assert result == 1513573200


def test_returns_scientific_timestamp_string_if_present():
    video_data = {"timestamp": "1.5135732e9"}
    result = PendingList._extract_published(video_data)
    assert result == 1513573200


def test_returns_timestamp_if_present():
    video_data = {"timestamp": 1508457600}
    result = PendingList._extract_published(video_data)
    assert result == 1508457600


def test_returns_iso_date_if_upload_date_present():
    video_data = {"upload_date": "20171020"}
    result = PendingList._extract_published(video_data)

    dt = datetime.fromtimestamp(result, tz=timezone.utc)
    assert dt.year == 2017
    assert dt.month == 10
    assert dt.day == 20
    assert dt.hour == 0
    assert dt.minute == 0
    assert dt.second == 0


def test_returns_None_if_no_date_info():
    video_data = {}

    result = PendingList._extract_published(video_data)

    assert result is None


class TestTheQueueReadIsRepeatable:
    class FakePaginate:
        docs: dict = {}

        def __init__(self, index, data, **kwargs):
            self.index = index

        def get_results(self):
            return self.docs.get(self.index, [])

    def _paginate(self, monkeypatch, download, indexed):
        self.FakePaginate.docs = {
            "ta_download": download,
            "ta_video": indexed,
        }
        monkeypatch.setattr(queue, "IndexPaginate", self.FakePaginate)

    def test_a_second_read_keeps_the_indexed_ids(self, monkeypatch):
        download = [{"youtube_id": "queued1", "status": "pending"}]
        self._paginate(monkeypatch, download, [{"youtube_id": "indexed1"}])

        pending = PendingIndex()
        pending.get_download()
        pending.get_indexed()

        download.append({"youtube_id": "ignored1", "status": "ignore"})
        pending.get_download()

        assert "indexed1" in pending.to_skip
        assert "ignored1" in pending.to_skip

    def test_a_second_read_replaces_the_queue_it_read_before(
        self, monkeypatch
    ):
        download = [{"youtube_id": "queued1", "status": "pending"}]
        self._paginate(monkeypatch, download, [])

        pending = PendingIndex()
        pending.get_download()
        pending.get_indexed()

        download[:] = [{"youtube_id": "queued1", "status": "ignore"}]
        pending.get_download()

        assert pending.all_pending == []
        assert [i["youtube_id"] for i in pending.all_ignored] == ["queued1"]
        assert pending.to_skip.count("queued1") == 1

    def test_the_first_read_works_before_anything_is_indexed(
        self, monkeypatch
    ):
        self._paginate(
            monkeypatch, [{"youtube_id": "queued1", "status": "pending"}], []
        )

        pending = PendingIndex()
        pending.get_download()

        assert pending.to_skip == ["queued1"]

    def test_an_id_the_queue_drops_stays_skipped(self, monkeypatch):
        download = [{"youtube_id": "queued1", "status": "pending"}]
        self._paginate(monkeypatch, download, [])

        pending = PendingIndex()
        pending.get_download()
        pending.get_indexed()

        download.clear()
        pending.get_download()

        assert pending.all_pending == []
        assert "queued1" in pending.to_skip
