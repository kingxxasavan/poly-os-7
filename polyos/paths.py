"""Filesystem locations, for both an installed system and a source checkout."""

from __future__ import annotations

import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent
# Running from the git checkout (dev mode, nested session) vs. /usr/lib/polyos.
IN_REPO = (ROOT / "main.py").is_file() and (ROOT / "ui").is_dir()

SHARE = ROOT / "data" if IN_REPO else Path("/usr/share/polyos")
UI_DIR = ROOT / "ui" if IN_REPO else SHARE / "ui"
BIN_DIR = ROOT / "data" / "bin" if IN_REPO else Path("/usr/bin")
WALLPAPER_DIR = SHARE / "wallpapers"
OPENBOX_RC = SHARE / "openbox" / "rc.xml"
PICOM_CONF = SHARE / "picom" / "picom.conf"
XDG_DIR = SHARE / "xdg"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "polyos"


def state_dir() -> Path:
    path = _xdg("XDG_STATE_HOME", ".local/state") / "polyos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    path = Path(base) / "polyos" if base else Path(tempfile.gettempdir()) / f"polyos-{getpass.getuser()}"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def command(name: str) -> list[str]:
    """argv for one of the polyos-* entry points."""
    script = BIN_DIR / name
    return [sys.executable, str(script)] if IN_REPO else [str(script)]


# The shell publishes its port and token here so polyos-ctl (keybindings) can reach it.
def _runtime_file() -> Path:
    return runtime_dir() / "shell.json"


def write_runtime_info(info: dict) -> None:
    path = _runtime_file()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(info, fh)


def read_runtime_info() -> dict | None:
    try:
        return json.loads(_runtime_file().read_text("utf-8"))
    except (OSError, ValueError):
        return None


def clear_runtime_info(pid: int) -> None:
    info = read_runtime_info()
    if info and info.get("pid") == pid:
        _runtime_file().unlink(missing_ok=True)
