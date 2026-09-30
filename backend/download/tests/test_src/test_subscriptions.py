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
    assert _is_due(item, "next_check", now_epoch=2000) is True


def test_is_due_false():
    item = {"next_check": 3000}
    assert _is_due(item, "next_check", now_epoch=2000) is False


def test_is_due_equal_is_due():
    item = {"next_check": 2000}
    assert _is_due(item, "next_check", now_epoch=2000) is True


def test_compute_next_check_no_jitter_is_exact():
    now = datetime(2026, 1, 1, 0, 0, 0)
    result = _compute_next_check(frequency_hours=24, jitter_percent=0, now=now)
    expected = int(datetime(2026, 1, 2, 0, 0, 0).timestamp())
    assert result == expected


@pytest.mark.parametrize("_run", range(20))
def test_compute_next_check_within_jitter_bounds(_run):
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
    now = datetime(2026, 1, 1, 0, 0, 0)
    now_epoch = int(now.timestamp())

    result = _compute_next_check(
        frequency_hours=1, jitter_percent=100, now=now
    )

    floor = now_epoch + int(MIN_INTERVAL_HOURS * 3600)
    assert result >= floor
