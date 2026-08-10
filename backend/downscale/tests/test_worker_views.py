"""
tests for _get_worker_name() - the worker-identity resolution shared by
every worker-facing job-scoped endpoint. Everything else in
worker_views.py is thin request/response glue over downscale.src.worker
(tested directly in test_src/test_worker.py), matching this project's
convention of exercising src/-layer logic rather than the Django view/
HTTP layer itself (see test_views.py)
"""

from unittest.mock import MagicMock

from downscale.worker_views import _get_worker_name


def test_header_takes_priority_over_body():
    request = MagicMock()
    request.headers = {"X-TA-Worker": "gaming-pc"}
    request.content_type = "application/json"
    request.data = {"worker": "some-other-worker"}

    assert _get_worker_name(request) == "gaming-pc"


def test_falls_back_to_json_body_worker_field():
    request = MagicMock()
    request.headers = {}
    request.content_type = "application/json"
    request.data = {"worker": "gaming-pc"}

    assert _get_worker_name(request) == "gaming-pc"


def test_no_header_and_non_json_body_returns_none():
    """a raw-body upload (PUT result) has no JSON to fall back to"""
    request = MagicMock()
    request.headers = {}
    request.content_type = "application/octet-stream"

    assert _get_worker_name(request) is None
