import subprocess
from unittest.mock import patch

from common.src.env_settings import EnvironmentSettings
from downscale.src.encoder_capability import (
    EncoderCapabilityTest,
    _build_test_cmd,
)

VAAPI_DEVICE = "/dev/dri/renderD128"


def test_hw_encoder_keys_are_only_the_hardware_variants():
    assert EncoderCapabilityTest.HW_ENCODER_KEYS == [
        "h264_vaapi",
        "h265_vaapi",
        "av1_vaapi",
    ]


def test_build_test_cmd_uses_synthetic_source():
    cmd = _build_test_cmd("h264_vaapi", VAAPI_DEVICE)

    assert cmd[:4] == [
        "ffmpeg",
        "-hide_banner",
        "-vaapi_device",
        VAAPI_DEVICE,
    ]
    assert "-f" in cmd
    assert cmd[cmd.index("-i") - 1] == "lavfi"
    assert cmd[cmd.index("-c:v") + 1] == "h264_vaapi"
    assert cmd[-3:] == ["-f", "null", "-"]


def test_build_test_cmd_h265_vaapi_maps_to_hevc_vaapi():
    cmd = _build_test_cmd("h265_vaapi", VAAPI_DEVICE)

    assert cmd[cmd.index("-c:v") + 1] == "hevc_vaapi"


def test_run_reports_missing_device_without_invoking_ffmpeg():
    with patch.object(
        EnvironmentSettings, "VAAPI_RENDER_DEVICE", "/dev/dri/does-not-exist"
    ), patch("downscale.src.encoder_capability.subprocess.run") as mock_run:
        results = EncoderCapabilityTest().run()

    mock_run.assert_not_called()
    assert [
        r["encoder"] for r in results
    ] == EncoderCapabilityTest.HW_ENCODER_KEYS
    for result in results:
        assert result["ok"] is False
        assert "not found" in result["message"]


def test_run_tests_each_encoder_when_device_present():
    with patch.object(
        EnvironmentSettings, "VAAPI_RENDER_DEVICE", VAAPI_DEVICE
    ), patch(
        "downscale.src.downscale.os.path.exists", return_value=True
    ), patch(
        "downscale.src.encoder_capability.subprocess.run"
    ) as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        results = EncoderCapabilityTest().run()

    assert mock_run.call_count == 3
    assert [
        r["encoder"] for r in results
    ] == EncoderCapabilityTest.HW_ENCODER_KEYS
    assert all(r["ok"] for r in results)


def test_test_one_success():
    with patch("downscale.src.encoder_capability.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        result = EncoderCapabilityTest()._test_one("h264_vaapi", VAAPI_DEVICE)

    assert result == {"encoder": "h264_vaapi", "ok": True, "message": None}


def test_test_one_failure_captures_stderr():
    with patch("downscale.src.encoder_capability.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="some ffmpeg error\n"
        )
        result = EncoderCapabilityTest()._test_one("av1_vaapi", VAAPI_DEVICE)

    assert result["encoder"] == "av1_vaapi"
    assert result["ok"] is False
    assert result["message"] == "some ffmpeg error"


def test_test_one_timeout():
    with patch(
        "downscale.src.encoder_capability.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=15),
    ):
        result = EncoderCapabilityTest()._test_one("h265_vaapi", VAAPI_DEVICE)

    assert result["ok"] is False
    assert "timed out" in result["message"]
