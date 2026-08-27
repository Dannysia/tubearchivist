"""test the ping payload carries build metadata safely

an image built without the TA_BUILD_* build args reports empty strings,
so the serializer has to pass those through rather than reject them -
that is the shape a plain docker build produces
"""

import pytest
from common.serializers import PingSerializer


def build_payload(**overwrites):
    """a ping response"""
    payload = {
        "response": "pong",
        "user": 1,
        "version": "v0.5.11",
        "build_sha": "52ef730f",
        "build_date": "2026-08-26T14:02:00Z",
    }
    payload.update(overwrites)

    return payload


def test_serializes_a_built_image():
    """sha and date from the build args"""
    data = PingSerializer(build_payload()).data

    assert data["build_sha"] == "52ef730f"
    assert data["build_date"] == "2026-08-26T14:02:00Z"


def test_serializes_a_dirty_build():
    """a build from a modified working tree is marked"""
    data = PingSerializer(build_payload(build_sha="52ef730f-dirty")).data

    assert data["build_sha"] == "52ef730f-dirty"


def test_serializes_an_image_built_without_the_args():
    """empty is valid, the frontend then shows the version alone"""
    data = PingSerializer(build_payload(build_sha="", build_date="")).data

    assert data["build_sha"] == ""
    assert data["build_date"] == ""


@pytest.mark.parametrize("field", ["build_sha", "build_date"])
def test_accepts_blank_build_fields_on_input(field):
    """blank must not raise, it is the unbuilt default"""
    serializer = PingSerializer(data=build_payload(**{field: ""}))
    serializer.is_valid(raise_exception=True)

    assert serializer.validated_data[field] == ""
