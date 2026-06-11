"""Platform detection for Haven.

Detects the runtime environment so platform-specific features
(GPIO, OLED, WSL path translation, etc.) can be toggled cleanly
without polluting core logic.

Usage::

    from core.platform import detect, Platform, is_wsl, supports_gpio

    if supports_gpio():
        from tools.oled_dashboard import launch
"""

from __future__ import annotations

import platform as _platform
from enum import Enum


class Platform(Enum):
    """Normalised platform identifiers."""

    WSL2 = "wsl2"
    LINUX_ARM64 = "linux_arm64"
    LINUX_AMD64 = "linux_amd64"
    MACOS = "macos"
    UNKNOWN = "unknown"


def detect() -> Platform:
    """Auto-detect the current platform."""
    system = _platform.system()
    machine = _platform.machine()

    if system == "Linux":
        if "microsoft" in _platform.uname().release.lower():
            return Platform.WSL2
        if machine in ("aarch64", "arm64"):
            return Platform.LINUX_ARM64
        if machine in ("x86_64", "amd64"):
            return Platform.LINUX_AMD64
        return Platform.UNKNOWN

    if system == "Darwin":
        return Platform.MACOS

    return Platform.UNKNOWN


def is_wsl() -> bool:
    """True when running under Windows Subsystem for Linux."""
    return detect() == Platform.WSL2


def supports_gpio() -> bool:
    """True only on ARM64 Linux boards (Orange Pi / Raspberry Pi)."""
    return detect() == Platform.LINUX_ARM64
