"""per channel overwrite keys

When the serializer's key list and set_overwrites' disagree, an update
validates cleanly and then raises deep in the writer - a 500 with an
empty body, not a 400 naming the bad key.
"""

# flake8: noqa: E402

import os
from types import SimpleNamespace

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from channel.serializers import ChannelOverwriteSerializer
from channel.src.constants import OVERWRITE_KEYS
from channel.src.index import YoutubeChannel


def a_channel(overwrites=None):
    """a channel stand in carrying just the json set_overwrites touches"""
    json_data = {"channel_id": "chan1"}
    if overwrites is not None:
        json_data["channel_overwrites"] = overwrites

    return SimpleNamespace(
        json_data=json_data, set_overwrites=YoutubeChannel.set_overwrites
    )


class TestOverwriteKeys:
    def test_every_serializer_field_is_writable(self):
        declared = set(ChannelOverwriteSerializer().fields)

        assert declared == set(OVERWRITE_KEYS)


class TestSetOverwrites:
    def test_writes_a_new_key(self):
        channel = a_channel()
        YoutubeChannel.set_overwrites(
            channel, {"subscriptions_channel_size": 50}
        )

        assert channel.json_data["channel_overwrites"] == {
            "subscriptions_channel_size": 50
        }

    def test_merges_into_what_is_already_there(self):
        channel = a_channel({"download_format": "bestvideo"})
        YoutubeChannel.set_overwrites(
            channel, {"subscriptions_channel_size": 50}
        )

        assert channel.json_data["channel_overwrites"] == {
            "download_format": "bestvideo",
            "subscriptions_channel_size": 50,
        }

    def test_a_null_clears_the_key(self):
        channel = a_channel({"subscriptions_channel_size": 50})
        YoutubeChannel.set_overwrites(
            channel, {"subscriptions_channel_size": None}
        )

        assert channel.json_data["channel_overwrites"] == {}

    def test_rejects_a_key_it_does_not_know(self):
        channel = a_channel()
        with pytest.raises(ValueError, match="invalid overwrite key"):
            YoutubeChannel.set_overwrites(channel, {"nonsense": 1})


class TestDownscaleTarget:
    def test_is_a_writable_overwrite(self):
        assert "downscale_target_height" in OVERWRITE_KEYS
        assert "downscale_target_height" in ChannelOverwriteSerializer().fields

    def test_accepts_a_height_on_the_ladder(self):
        serializer = ChannelOverwriteSerializer(
            data={"downscale_target_height": 1080}
        )

        assert serializer.is_valid(), serializer.errors

    def test_accepts_null_to_clear(self):
        serializer = ChannelOverwriteSerializer(
            data={"downscale_target_height": None}
        )

        assert serializer.is_valid(), serializer.errors

    def test_rejects_a_height_off_the_ladder(self):
        """the downscale queue only knows the ladder heights"""
        serializer = ChannelOverwriteSerializer(
            data={"downscale_target_height": 900}
        )

        assert not serializer.is_valid()
        assert "downscale_target_height" in serializer.errors
