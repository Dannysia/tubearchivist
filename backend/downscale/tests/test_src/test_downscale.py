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
        "medium",
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
    assert "-quality" not in cmd
    assert "-global_quality" not in cmd


@pytest.mark.parametrize(
    "encoder_key,expected_codec,expected_rc_mode,expected_quality_flag",
    [
        ("h264_vaapi", "h264_vaapi", "CQP", "-qp"),
        ("h265_vaapi", "hevc_vaapi", "CQP", "-qp"),
        ("av1_vaapi", "av1_vaapi", "ICQ", "-global_quality"),
    ],
)
def test_hardware_cmd_uses_vaapi_pipeline(
    encoder_key, expected_codec, expected_rc_mode, expected_quality_flag
):
    """
    hardware encoders keep software decode/scale, upload to a vaapi
    surface. h264_vaapi/h265_vaapi use CQP+-qp; av1_vaapi doesn't
    support -qp/CQP in ffmpeg, so it uses ICQ+-global_quality instead
    """
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        encoder_key,
        23,
        "medium",
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
    assert cmd[cmd.index("-rc_mode") + 1] == expected_rc_mode
    assert expected_quality_flag in cmd
    assert cmd[cmd.index(expected_quality_flag) + 1] == "23"
    assert "-crf" not in cmd

    other_quality_flag = (
        "-global_quality" if expected_quality_flag == "-qp" else "-qp"
    )
    assert other_quality_flag not in cmd


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
        "medium",
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
        "medium",
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert cmd[cmd.index("-c:v") + 1] == "libx264"


@pytest.mark.parametrize(
    "encoder_key,preset,expected_flag,expected_value",
    [
        ("h264", "veryfast", "-preset", "veryfast"),
        ("h264", "placebo", "-preset", "placebo"),
        ("h265", "slow", "-preset", "slow"),
        # libsvtav1 has no named presets, so the chosen name is mapped
        # onto its own 0 (slowest/best) - 13 (fastest) numeric scale
        ("av1", "veryfast", "-preset", "8"),
        ("av1", "placebo", "-preset", "0"),
        # h264_vaapi's -quality is Intel's Target Usage (1 best/slowest -
        # 7 fastest/worst), a much narrower range than the named presets
        ("h264_vaapi", "medium", "-quality", "4"),
        ("h264_vaapi", "ultrafast", "-quality", "7"),
        ("h264_vaapi", "veryslow", "-quality", "1"),
    ],
)
def test_preset_maps_onto_whatever_speed_knob_the_encoder_supports(
    encoder_key, preset, expected_flag, expected_value
):
    """named preset is translated per-encoder, not passed through as-is"""
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        encoder_key,
        23,
        preset,
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert expected_flag in cmd
    assert cmd[cmd.index(expected_flag) + 1] == expected_value


@pytest.mark.parametrize("encoder_key", ["h265_vaapi", "av1_vaapi"])
def test_preset_has_no_effect_on_encoders_without_a_speed_knob(encoder_key):
    """h265_vaapi/av1_vaapi expose no -preset/-quality option in ffmpeg"""
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        encoder_key,
        23,
        "veryslow",
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert "-preset" not in cmd
    assert "-quality" not in cmd


def test_no_preset_omits_speed_flags():
    """preset=None adds no speed-related flag at all"""
    cmd = _build_ffmpeg_cmd(
        "/youtube/original.mp4",
        720,
        "h264",
        23,
        None,
        "/cache/downscale/tmp.mp4",
        VAAPI_DEVICE,
    )

    assert "-preset" not in cmd
