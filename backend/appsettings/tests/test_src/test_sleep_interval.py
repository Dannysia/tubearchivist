"""the sleep interval setting, which paces every youtube facing queue"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.serializers import AppConfigDownloadsSerializer
from common.src.helper import MIN_SLEEP_INTERVAL


def _validate(sleep_interval):
    serializer = AppConfigDownloadsSerializer(
        data={"sleep_interval": sleep_interval}, partial=True
    )

    return serializer


@pytest.mark.parametrize("value", [1, 2, 3, 4])
def test_rejects_an_interval_too_low_to_pace(value):
    serializer = _validate(value)

    assert not serializer.is_valid()
    assert "sleep_interval" in serializer.errors


@pytest.mark.parametrize("value", [MIN_SLEEP_INTERVAL, 10, 60])
def test_accepts_the_minimum_and_above(value):
    serializer = _validate(value)

    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize("value", [None, 0])
def test_disabling_pacing_stays_allowed(value):
    serializer = _validate(value)

    assert serializer.is_valid(), serializer.errors
