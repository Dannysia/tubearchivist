"""tests for ffmpeg command construction"""

import pytest
from downscale.src.downscale import (
    _build_ffmpeg_cmd,
    is_hw_encoder,
    missing_vaapi_device_message,
)

VAAPI_DEVICE = "/dev/dri/renderD128"


@pytest.mark.parametrize(
    "encoder_key,expected",
    [
        ("h264", False),
        ("h265", False),
        ("av1", False),
        ("h264_vaapi", True),
        ("h265_vaapi", True),
        ("av1_vaapi", True),
    ],
)
def test_is_hw_encoder(encoder_key, expected):
    """hardware encoder keys all carry a _vaapi suffix"""
    assert is_hw_encoder(encoder_key) is expected


def test_missing_vaapi_device_message_when_present(tmp_path):
    """an existing device path reports no problem"""
    device = tmp_path / "renderD128"
    device.touch()

    assert missing_vaapi_device_message(str(device)) is None


def test_missing_vaapi_device_message_when_absent():
    """a missing device path reports an actionable message"""
    message = missing_vaapi_device_message("/dev/dri/does-not-exist")

    assert message is not None
    assert "/dev/dri/does-not-exist" in message
    assert "not found" in message


@pytest.mark.parametrize(
    "encoder_key,expected_codec",
    [
        ("h264", "libx264"),
        ("h265", "libx265"),
        ("av1", "libsvtav1"),
    ],
)
def test_software_cmd_has_no_hw_flags(encoder_key, expected_codec):
    """software encoders scale in one step and use -crf"""
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        encoder_key,
        23,
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert "-vaapi_device" not in cmd
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == expected_codec

    assert "-vf" in cmd
    assert cmd[cmd.index("-vf") + 1] == "scale=-2:720"

    assert "-crf" in cmd
    assert cmd[cmd.index("-crf") + 1] == "23"
    assert "-qp" not in cmd
    assert "-rc_mode" not in cmd


@pytest.mark.parametrize(
    "encoder_key,expected_codec",
    [
        ("h264_vaapi", "h264_vaapi"),
        ("h265_vaapi", "hevc_vaapi"),
        ("av1_vaapi", "av1_vaapi"),
    ],
)
def test_hardware_cmd_uses_vaapi_pipeline(encoder_key, expected_codec):
    """
    hardware encoders keep software decode/scale, upload to a vaapi
    surface, and use an explicit CQP rate control with -qp
    """
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        encoder_key,
        23,
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert "-vaapi_device" in cmd
    vaapi_device_idx = cmd.index("-vaapi_device")
    assert cmd[vaapi_device_idx + 1] == VAAPI_DEVICE
    assert vaapi_device_idx < cmd.index("-i")

    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == expected_codec

    assert "-vf" in cmd
    assert cmd[cmd.index("-vf") + 1] == "scale=-2:720,format=nv12,hwupload"

    assert "-rc_mode" in cmd
    assert cmd[cmd.index("-rc_mode") + 1] == "CQP"
    assert "-qp" in cmd
    assert cmd[cmd.index("-qp") + 1] == "23"
    assert "-crf" not in cmd


def test_h265_vaapi_maps_to_hevc_vaapi_not_h265_vaapi():
    """
    ffmpeg has no encoder literally named h265_vaapi, only hevc_vaapi -
    guard against reintroducing that mixup
    """
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        "h265_vaapi",
        23,
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert cmd[cmd.index("-c:v") + 1] == "hevc_vaapi"
    assert "-tag:v" in cmd
    assert cmd[cmd.index("-tag:v") + 1] == "hvc1"


def test_unknown_encoder_falls_back_to_h264():
    """unknown encoder key defaults to software h264"""
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        "not-a-real-encoder",
        23,
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert cmd[cmd.index("-c:v") + 1] == "libx264"
