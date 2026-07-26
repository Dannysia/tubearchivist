"""tests for per-subscription scheduling functions"""

from datetime import datetime

import pytest
from download.src.subscriptions import (
    MIN_INTERVAL_HOURS,
    _compute_next_check,
    _is_due,
)


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"next_check": None},
        {"next_check": 0},
        {"next_check": 1000},
    ],
)
def test_is_due_true(item):
    """missing, falsy, or past next_check is due"""
    assert _is_due(item, "next_check", now_epoch=2000) is True


def test_is_due_false():
    """future next_check is not due"""
    item = {"next_check": 3000}
    assert _is_due(item, "next_check", now_epoch=2000) is False


def test_is_due_equal_is_due():
    """next_check exactly now is due"""
    item = {"next_check": 2000}
    assert _is_due(item, "next_check", now_epoch=2000) is True


def test_compute_next_check_no_jitter_is_exact():
    """zero jitter always lands exactly on frequency_hours"""
    now = datetime(2026, 1, 1, 0, 0, 0)
    result = _compute_next_check(frequency_hours=24, jitter_percent=0, now=now)
    expected = int(datetime(2026, 1, 2, 0, 0, 0).timestamp())
    assert result == expected


@pytest.mark.parametrize("_run", range(20))
def test_compute_next_check_within_jitter_bounds(_run):
    """result stays within frequency_hours * (1 +/- jitter_percent/100)"""
    now = datetime(2026, 1, 1, 0, 0, 0)
    now_epoch = int(now.timestamp())
    frequency_hours = 24
    jitter_percent = 25

    result = _compute_next_check(frequency_hours, jitter_percent, now=now)

    lower = now_epoch + int(frequency_hours * 0.75 * 3600)
    upper = now_epoch + int(frequency_hours * 1.25 * 3600)
    assert lower <= result <= upper


@pytest.mark.parametrize("_run", range(20))
def test_compute_next_check_never_below_floor(_run):
    """low frequency + high jitter never drops below MIN_INTERVAL_HOURS"""
    now = datetime(2026, 1, 1, 0, 0, 0)
    now_epoch = int(now.timestamp())

    result = _compute_next_check(
        frequency_hours=1, jitter_percent=100, now=now
    )

    floor = now_epoch + int(MIN_INTERVAL_HOURS * 3600)
    assert result >= floor
