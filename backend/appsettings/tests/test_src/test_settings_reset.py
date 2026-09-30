"""test that the nullable settings accept null"""

# flake8: noqa: E402

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pytest
from appsettings.serializers import (
    AppConfigAppSerializer,
    AppConfigDownloadsSerializer,
)


@pytest.mark.parametrize(
    "serializer_class, field",
    [
        (AppConfigAppSerializer, "log_retention_days"),
        (AppConfigDownloadsSerializer, "max_exit_node_rotates"),
    ],
)
def test_null_resets_the_setting(serializer_class, field):
    serializer = serializer_class(data={field: None}, partial=True)

    assert serializer.is_valid(), serializer.errors
