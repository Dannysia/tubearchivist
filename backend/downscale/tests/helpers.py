from unittest.mock import MagicMock

from downscale.src.downscale import DownscaleRunner


def mock_lock(acquired=True):
    lock = MagicMock()
    lock.acquire.return_value = acquired
    return lock


def make_runner(task=None):
    return DownscaleRunner(
        task=task, youtube_id="video1", target_height=480, doc_id="doc1"
    )
