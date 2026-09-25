"""Settings store, event bus and small shared helpers."""

from __future__ import annotations

import copy
import json
import logging
import os
import queue
import re
import threading
import zlib
from html import escape
from pathlib import Path

log = logging.getLogger("polyos")


class ApiError(Exception):
    """An error whose message is safe to show to the user."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


IMAGE_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

DEFAULTS: dict = {
    "theme": "dark",  # "dark" | "light" (PolyOS 7's Appearance choice)
    "accent": "#678fd9",
    "wallpaper": "builtin:polyos-prism.jpg",  # the PolyOS 7 crystal
    "lockWallpaper": "builtin:polyos-amethyst.jpg",  # login and lock screen (shown blurred)
    "clock24h": False,
    "showSeconds": False,
    "desktopClock": False,
    "desktopIcons": ["polyos-files.desktop", "firefox-esr.desktop", "polyos-store.desktop"],  # shortcuts on the wallpaper
    "desktopOpen": "double",  # "double" | "single": clicks to open a desktop shortcut
    "pinned": [
        "firefox-esr.desktop",
        "polyos-files.desktop",
        "polyos-store.desktop",
        "xfce4-terminal.desktop",
        "org.xfce.mousepad.desktop",
        "polyos-settings.desktop",
    ],
    "setupDone": False,  # first-run setup ("It's time to get started") finished
    "recent": [],  # most recently opened apps, newest first (Start menu)
    "effects": True,  # compositor: blur, shadows, rounded corners (next sign-in)
    "glass": 78,  # opacity of the dock and popups in percent (lower = more see-through)
    "scale": "auto",  # "auto" | "1" | "2" (next sign-in)
    "showAllApps": False,  # list the technical apps PolyOS hides from the launcher
    "widgets": ["weather", "calendar", "system", "news", "todo", "photos"],  # the widgets board, in order
    # Taskbar (Settings > Taskbar)
    "taskbarStyle": "floating",  # "floating" capsule | "full": edge to edge, maximized windows meet it
    "taskbarAlign": "center",  # "center" | "left": where the app icons sit
    "taskbarAutoHide": False,  # hide until the pointer touches the bottom edge; maximized windows fill the screen
    "taskbarWidgets": True,  # weather / widgets button
    "taskbarDate": True,  # date under the clock
    # Power (Settings > Power)
    "powerMode": "balanced",  # "saver" | "balanced" | "performance" | "maximum"
    "screenOff": 10,  # minutes of inactivity before the screen turns off (0 = never)
    "sleepAfter": 30,  # minutes of inactivity before the computer sleeps (0 = never)
    # Security and privacy
    "lockOnSleep": True,  # lock when the computer sleeps or the screen turns off
    "lockNews": True,  # headlines and performance on the lock screen
    "cameraAccess": True,
    "micAccess": True,
    "keepRecent": True,  # remember recently opened apps for the Home Menu
}
POWER_MODES = ("saver", "balanced", "performance", "maximum")
SCREEN_OFF_CHOICES = (0, 1, 2, 3, 5, 10, 15, 30, 60)
SLEEP_CHOICES = (0, 5, 10, 15, 30, 60, 120, 240)
WIDGET_IDS = ("weather", "calendar", "system", "news", "todo", "notes", "photos", "clocks", "media")

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_DESKTOP_ID = re.compile(r"^[\w.+@-]{1,200}\.desktop$")
_BUILTIN = re.compile(r"^builtin:[\w-][\w.-]{0,99}$")


def _bool(value):
    if isinstance(value, bool):
        return value
    raise ValueError("expected true or false")


def _accent(value):
    if isinstance(value, str) and _HEX.match(value):
        return value.lower()
    raise ValueError("expected a #rrggbb color")


def _wallpaper(value):
    if isinstance(value, str):
        if _BUILTIN.match(value) and ".." not in value:
            return value
        path = Path(value)
        if path.is_absolute() and path.suffix.lower() in IMAGE_TYPES and path.is_file():
            return str(path)
    raise ValueError("expected a built-in wallpaper or an existing image file")


def _pinned(value):
    if not isinstance(value, list) or len(value) > 24:
        raise ValueError("expected a list of up to 24 app ids")
    out = []
    for item in value:
        if not isinstance(item, str) or not _DESKTOP_ID.match(item):
            raise ValueError(f"invalid app id: {item!r}")
        if item not in out:
            out.append(item)
    return out


def _glass(value):
    if isinstance(value, int) and not isinstance(value, bool) and 30 <= value <= 100:
        return value
    raise ValueError("expected a whole number from 30 to 100")


def _widgets(value):
    if isinstance(value, list) and len(value) <= len(WIDGET_IDS) and len(set(value)) == len(value) \
            and all(v in WIDGET_IDS for v in value):
        return value
    raise ValueError(f"expected a list of widgets from: {', '.join(WIDGET_IDS)}")


def _choice(*choices):
    def check(value):
        if value in choices and not isinstance(value, bool):
            return value
        raise ValueError("expected one of: " + ", ".join(map(str, choices)))
    return check


def _theme(value):
    if value in ("dark", "light"):
        return value
    raise ValueError("expected dark or light")


def _scale(value):
    if value in ("auto", "1", "2"):
        return value
    raise ValueError("expected auto, 1 or 2")


VALIDATORS = {
    "theme": _theme,
    "showAllApps": _bool,
    "widgets": _widgets,
    "accent": _accent,
    "wallpaper": _wallpaper,
    "clock24h": _bool,
    "showSeconds": _bool,
    "desktopClock": _bool,
    "lockWallpaper": _wallpaper,
    "desktopIcons": _pinned,
    "desktopOpen": _choice("double", "single"),
    "taskbarStyle": _choice("floating", "full"),
    "taskbarAlign": _choice("center", "left"),
    "taskbarAutoHide": _bool,
    "taskbarWidgets": _bool,
    "taskbarDate": _bool,
    "powerMode": _choice(*POWER_MODES),
    "screenOff": _choice(*SCREEN_OFF_CHOICES),
    "sleepAfter": _choice(*SLEEP_CHOICES),
    "lockOnSleep": _bool,
    "lockNews": _bool,
    "cameraAccess": _bool,
    "micAccess": _bool,
    "keepRecent": _bool,
    "pinned": _pinned,
    "recent": _pinned,
    "setupDone": _bool,
    "effects": _bool,
    "glass": _glass,
    "scale": _scale,
}


class Settings:
    """User preferences in ~/.config/polyos/settings.json. Thread-safe."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data = copy.deepcopy(DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable settings file %s: %s", self.path, exc)
            return
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            if key in VALIDATORS:
                try:
                    self._data[key] = VALIDATORS[key](value)
                except ValueError as exc:
                    log.warning("ignoring setting %s: %s", key, exc)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, key: str):
        with self._lock:
            return copy.deepcopy(self._data[key])

    def update(self, patch: dict) -> dict:
        if not isinstance(patch, dict) or not patch:
            raise ApiError("expected an object of settings")
        clean = {}
        for key, value in patch.items():
            if key not in VALIDATORS:
                raise ApiError(f"unknown setting: {key}")
            try:
                clean[key] = VALIDATORS[key](value)
            except ValueError as exc:
                raise ApiError(f"{key}: {exc}") from None
        with self._lock:
            self._data.update(clean)
            self._save_locked()
            return copy.deepcopy(self._data)

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2) + "\n", "utf-8")
        os.replace(tmp, self.path)


class EventBus:
    """Fan-out of JSON events to every connected UI surface."""

    def __init__(self):
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def is_subscribed(self, q: queue.Queue) -> bool:
        with self._lock:
            return q in self._subs

    def publish(self, type_: str, **payload) -> None:
        data = json.dumps({"type": type_, **payload}, separators=(",", ":")).encode()
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                # A stalled client; dropping it makes it reconnect and resync.
                self.unsubscribe(q)


def letter_icon(name: str) -> bytes:
    """Fallback app icon: a colored tile with the app's initial."""
    hue = zlib.crc32(name.encode()) % 360
    letter = escape((name.strip()[:1] or "?").upper())
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue},72%,62%)"/>'
        f'<stop offset="1" stop-color="hsl({(hue + 40) % 360},68%,46%)"/>'
        "</linearGradient></defs>"
        '<rect x="4" y="4" width="56" height="56" rx="16" fill="url(#g)"/>'
        '<text x="32" y="42.5" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" '
        f'font-size="28" font-weight="700" fill="#fff">{letter}</text></svg>'
    ).encode()
