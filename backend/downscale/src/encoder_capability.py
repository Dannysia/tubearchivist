"""
functionality:
- test whether each hardware encoder actually works on this machine, not
  just whether ffmpeg knows the encoder name
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor

from common.src.env_settings import EnvironmentSettings
from downscale.src.downscale import (
    ENCODER_SETTINGS,
    _encode_args,
    is_hw_encoder,
    missing_vaapi_device_message,
)

TEST_TIMEOUT = 15
TEST_QUALITY = 23
TEST_SOURCE = "testsrc=duration=1:size=1280x720:rate=30"


def _build_test_cmd(encoder_key: str, vaapi_device: str) -> list[str]:
    """
    build a minimal ffmpeg command to test if a hardware encoder actually
    works on this machine, using a synthetic 1-second test pattern instead
    of a real source file
    """
    cmd = ["ffmpeg", "-hide_banner", "-vaapi_device", vaapi_device]
    cmd += ["-f", "lavfi", "-i", TEST_SOURCE]
    cmd += ["-vf", "format=nv12,hwupload"]
    cmd += _encode_args(encoder_key, TEST_QUALITY)
    cmd += ["-f", "null", "-"]

    return cmd


class EncoderCapabilityTest:
    """
    run a small synthetic encode for each hardware encoder to check if it
    actually works on this machine, not just whether ffmpeg knows the
    encoder name - catches missing device passthrough, a driver that
    isn't loaded, or a codec/hardware combo the GPU doesn't support
    """

    HW_ENCODER_KEYS = [key for key in ENCODER_SETTINGS if is_hw_encoder(key)]

    def run(self) -> list[dict]:
        """
        test all hardware encoders, return one result dict per encoder.
        Encoders are independent of each other, so they're tested
        concurrently rather than one after another.
        """
        vaapi_device = EnvironmentSettings.VAAPI_RENDER_DEVICE
        missing_message = missing_vaapi_device_message(vaapi_device)
        if missing_message:
            return [
                {"encoder": key, "ok": False, "message": missing_message}
                for key in self.HW_ENCODER_KEYS
            ]

        with ThreadPoolExecutor(max_workers=len(self.HW_ENCODER_KEYS)) as pool:
            return list(
                pool.map(
                    lambda key: self._test_one(key, vaapi_device),
                    self.HW_ENCODER_KEYS,
                )
            )

    def _test_one(self, encoder_key: str, vaapi_device: str) -> dict:
        """test a single hardware encoder, assumes the device exists"""
        cmd = _build_test_cmd(encoder_key, vaapi_device)
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=TEST_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "encoder": encoder_key,
                "ok": False,
                "message": f"test encode timed out after {TEST_TIMEOUT}s",
            }

        if result.returncode == 0:
            return {"encoder": encoder_key, "ok": True, "message": None}

        return {
            "encoder": encoder_key,
            "ok": False,
            "message": result.stderr.strip()[-500:],
        }
