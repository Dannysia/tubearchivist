from download.src.extraction_queue import ExtractionQueue

MAX_PASSES = 25


def entry_doc(name, auto_start=False):
    return {
        "item_type": "channel",
        "youtube_id": f"UC_{name}",
        "vid_type": None,
        "limit": None,
        "auto_start": auto_start,
        "flat": False,
        "force": False,
        "target_status": "pending",
    }


def queue_of(monkeypatch, names: list[str]):
    """returns (the queue, a counter of _get_next calls)"""
    remaining = list(names)
    passes = {"n": 0}

    def fake_next():
        passes["n"] += 1
        if passes["n"] > MAX_PASSES or not remaining:
            return None, None

        name = remaining.pop(0)
        return name, entry_doc(name)

    monkeypatch.setattr(ExtractionQueue, "_get_next", staticmethod(fake_next))
    monkeypatch.setattr(
        ExtractionQueue, "has_work", classmethod(lambda cls: True)
    )
    return ExtractionQueue(), passes
