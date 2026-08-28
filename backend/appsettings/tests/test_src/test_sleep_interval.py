"""the sleep interval setting, which paces every youtube facing queue

At 1 the randomised window collapses to always zero, so a value the API
used to accept turned pacing off entirely without saying so. 2 to 4 do
pace, just too little to be worth having the setting - 4 spreads
requests over 2-5s - so the floor sits at 5 for all of them.
"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.serializers import AppConfigDownloadsSerializer
from common.src.helper import MIN_SLEEP_INTERVAL


def _validate(sleep_interval):
    """partial, so only the field under test has to be present

    This is how the settings page updates it - one field at a time.
    """
    serializer = AppConfigDownloadsSerializer(
        data={"sleep_interval": sleep_interval}, partial=True
    )

    return serializer


@pytest.mark.parametrize("value", [1, 2, 3, 4])
def test_rejects_an_interval_too_low_to_pace(value):
    """1 randranges to 0 every time; the rest are too narrow to matter"""
    serializer = _validate(value)

    assert not serializer.is_valid()
    assert "sleep_interval" in serializer.errors


@pytest.mark.parametrize("value", [MIN_SLEEP_INTERVAL, 10, 60])
def test_accepts_the_minimum_and_above(value):
    serializer = _validate(value)

    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize("value", [None, 0])
def test_disabling_pacing_stays_allowed(value):
    """null and 0 both mean off, and 0 predates the floor

    rand_sleep_secs treats them identically, so rejecting 0 would lock
    anyone already using it out of their own settings page.
    """
    serializer = _validate(value)

    assert serializer.is_valid(), serializer.errors
