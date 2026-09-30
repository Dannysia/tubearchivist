from unittest.mock import MagicMock

from downscale.worker_views import _get_worker_name


def test_the_header_names_the_worker():
    request = MagicMock()
    request.headers = {"X-TA-Worker": "gaming-pc"}

    assert _get_worker_name(request) == "gaming-pc"


def test_a_json_body_does_not_name_the_worker():
    request = MagicMock()
    request.headers = {}
    request.content_type = "application/json"
    request.data = {"worker": "gaming-pc"}

    assert _get_worker_name(request) is None
