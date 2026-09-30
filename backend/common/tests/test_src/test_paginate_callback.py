"""test IndexPaginate's result handling with and without a callback"""

from common.src import es_connect
from common.src.es_connect import IndexPaginate

PAGES = [
    [{"_source": {"n": 1}, "sort": [1]}, {"_source": {"n": 2}, "sort": [2]}],
    [{"_source": {"n": 3}, "sort": [3]}],
    [],
]


class FakeWrap:
    served = []

    def __init__(self, path):
        pass

    def get(self, data=None, timeout=None):
        return {"hits": {"hits": FakeWrap.served.pop(0)}}, 200


class Task:
    def __init__(self):
        self.progress = []

    def send_progress(self, message, progress=None):
        self.progress.append(progress)


def _paginate(monkeypatch, **kwargs):
    FakeWrap.served = [list(page) for page in PAGES]
    monkeypatch.setattr(es_connect, "ElasticWrap", FakeWrap)
    paginate = IndexPaginate("ta_x", {"query": {"match_all": {}}}, **kwargs)
    paginate.data["sort"] = [{"_doc": {"order": "desc"}}]
    return paginate


def test_without_a_callback_every_hit_is_returned(monkeypatch):
    assert _paginate(monkeypatch).run_loop() == [{"n": 1}, {"n": 2}, {"n": 3}]


def test_a_callback_gets_every_page_and_nothing_is_held(monkeypatch):
    pages = []

    class Callback:
        def __init__(self, hits, index_name, counter=0):
            self.hits = hits

        def run(self):
            pages.append(len(self.hits))

    task = Task()
    paginate = _paginate(monkeypatch, callback=Callback, task=task, total=3)

    assert paginate.run_loop() == []
    assert pages == [2, 1]
    assert task.progress == [2 / 3, 1.0]
