"""Security checkup for Settings > Privacy & Security: firewall, updates, AppArmor, Secure Boot.

Everything here only reads world-readable files, so the shell can show it without asking for
a password. Changing the firewall or automatic updates goes through `polyos-admin security`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

UFW_CONF = Path("/etc/ufw/ufw.conf")
AUTO_UPGRADES = Path("/etc/apt/apt.conf.d/20auto-upgrades")
APPARMOR = Path("/sys/module/apparmor/parameters/enabled")
AUTO_UPGRADES_TEXT = ('// PolyOS: automatic security updates (Settings > Privacy & Security)\n'
                      'APT::Periodic::Update-Package-Lists "{on}";\nAPT::Periodic::Unattended-Upgrade "{on}";\n')


def _read(path: Path) -> str:
    try:
        return path.read_text("utf-8", "replace")
    except OSError:
        return ""


def firewall_enabled(text: str) -> bool:
    return bool(re.search(r"^\s*ENABLED\s*=\s*yes\s*$", text, re.M | re.I))


def updates_enabled(text: str) -> bool:
    m = re.search(r'APT::Periodic::Unattended-Upgrade\s+"(\d+)"', text)
    return bool(m) and m.group(1) != "0"


def status() -> dict:
    firewall = None if not (UFW_CONF.exists() or shutil.which("ufw")) else firewall_enabled(_read(UFW_CONF))
    updates = None if not Path("/usr/bin/unattended-upgrade").exists() else updates_enabled(_read(AUTO_UPGRADES))
    apparmor = _read(APPARMOR).strip().upper().startswith("Y") if APPARMOR.exists() else None
    secure_boot = None
    if Path("/sys/firmware/efi").is_dir() and shutil.which("mokutil"):
        try:
            out = subprocess.run(["mokutil", "--sb-state"], capture_output=True, text=True, timeout=5).stdout.lower()
            secure_boot = "enabled" in out
        except (OSError, subprocess.SubprocessError):
            pass
    return {"firewall": firewall, "updates": updates, "apparmor": apparmor, "secureBoot": secure_boot}


class Throttle:
    """Slows down password guessing on the lock screen: after 5 wrong tries, a wait that doubles."""

    def __init__(self, limit: int = 5, wait: float = 30, clock=None):
        import time

        self.limit, self.wait = limit, wait
        self.clock = clock or time.monotonic
        self.failures = 0
        self.until = 0.0

    def check(self) -> None:
        from .core import ApiError

        left = self.until - self.clock()
        if left > 0:
            raise ApiError(f"Too many wrong tries. Wait {int(left) + 1} seconds, then try again.", 429)

    def failed(self) -> None:
        self.failures += 1
        if self.failures >= self.limit:
            self.until = self.clock() + self.wait * 2 ** (self.failures - self.limit)

    def succeeded(self) -> None:
        self.failures = 0
        self.until = 0.0
