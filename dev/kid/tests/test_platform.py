"""Test core/platform.py — platform detection."""

import sys
from unittest.mock import patch

from core.platform import Platform, detect, is_wsl, supports_gpio


class TestDetect:
    def test_wsl2(self):
        with (
            patch("core.platform._platform.system", return_value="Linux"),
            patch("core.platform._platform.uname") as mock_uname,
            patch("core.platform._platform.machine", return_value="x86_64"),
        ):
            mock_uname.return_value.release = "5.15.90.1-microsoft-standard-WSL2"
            assert detect() == Platform.WSL2
            assert is_wsl() is True
            assert supports_gpio() is False

    def test_linux_arm64(self):
        with (
            patch("core.platform._platform.system", return_value="Linux"),
            patch("core.platform._platform.uname") as mock_uname,
            patch("core.platform._platform.machine", return_value="aarch64"),
        ):
            mock_uname.return_value.release = "5.10.160-rockchip"
            assert detect() == Platform.LINUX_ARM64
            assert is_wsl() is False
            assert supports_gpio() is True

    def test_linux_arm64_alt_machine(self):
        with (
            patch("core.platform._platform.system", return_value="Linux"),
            patch("core.platform._platform.uname") as mock_uname,
            patch("core.platform._platform.machine", return_value="arm64"),
        ):
            mock_uname.return_value.release = "5.10.160-rockchip"
            assert detect() == Platform.LINUX_ARM64

    def test_linux_amd64(self):
        with (
            patch("core.platform._platform.system", return_value="Linux"),
            patch("core.platform._platform.uname") as mock_uname,
            patch("core.platform._platform.machine", return_value="x86_64"),
        ):
            mock_uname.return_value.release = "6.1.0-18-amd64"
            assert detect() == Platform.LINUX_AMD64

    def test_macos(self):
        with (
            patch("core.platform._platform.system", return_value="Darwin"),
            patch("core.platform._platform.machine", return_value="arm64"),
        ):
            assert detect() == Platform.MACOS

    def test_unknown(self):
        with (
            patch("core.platform._platform.system", return_value="Windows"),
            patch("core.platform._platform.machine", return_value="AMD64"),
        ):
            assert detect() == Platform.UNKNOWN
