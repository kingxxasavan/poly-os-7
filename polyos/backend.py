"""The backend contract the web UI talks to, plus logic shared by every backend."""

from __future__ import annotations

import getpass
import json
import socket
import threading
import time
from pathlib import Path

from . import __version__, paths
from .core import DEFAULTS, IMAGE_TYPES, ApiError, EventBus, Settings
from .files import FileSystem
from .vara import Vara, complete

# Floating dock geometry in logical px. The dock window is the bar itself, inset from the
# screen edges; openbox keeps PANEL_HEIGHT (times the UI scale) free for maximized windows.
DOCK_HEIGHT = 52
DOCK_MARGIN = 8
PANEL_HEIGHT = DOCK_HEIGHT + DOCK_MARGIN + 4

# Popup sizes in logical px. "taskmenu" height is supplied by the panel (it depends on the items).
# Full-screen popups cover the monitor above the dock; their size is filled in by the shell.
FULLSCREEN_POPUPS = {"launcher", "power"}
POPUP_SIZES = {
    "start": (400, 596),  # the PolyOS Home Menu
    "launcher": (0, 0),
    "power": (0, 0),
    "run": (460, 188),
    "vara": (440, 600),
    "quick": (360, 326),  # the Wi-Fi list asks for more height via the "height" field
    "calendar": (320, 390),
    "taskmenu": (240, 200),
}
RECENT_LIMIT = 6
WALLPAPER_NAMES = {"polyos-dusk": "Dusk", "polyos-violet": "Violet", "polyos-night": "Night", "pixapoly": "PIXAPoLY"}
POWER_ACTIONS = ("lock", "logout", "suspend", "reboot", "poweroff")
RUN_TARGETS = ("terminal", "files", "browser")
OPEN_APPS = ("settings", "files", "setup")
# Clicking the button that opened a popup first blurs it (closing it) and then
# toggles it again; ignore a reopen of the same popup this soon after a close.
REOPEN_GUARD = 0.35


class Backend:
    """Subclasses: MockBackend (dev in a browser) and DesktopShell (the real session)."""

    dev = False

    def __init__(self, settings: Settings, bus: EventBus, home: Path | None = None):
        self.settings = settings
        self.bus = bus
        self.files = FileSystem(home or Path.home())
        self.vara = Vara(settings.path.parent / "vara.json")  # ~/.config/polyos/vara.json
        self._popup_lock = threading.Lock()
        self._popup: dict | None = None
        self._popup_key: str | None = None
        self._last_closed: tuple[str, float] | None = None

    # ---- implemented by subclasses -------------------------------------------------
    def apps(self) -> list[dict]: raise NotImplementedError
    def windows(self) -> list[dict]: raise NotImplementedError
    def launch(self, app_id: str): raise NotImplementedError
    def window_action(self, xid: int, action: str): raise NotImplementedError
    def system_status(self) -> dict: raise NotImplementedError
    def set_volume(self, level=None, delta=None, muted=None, toggle_mute=False): raise NotImplementedError
    def set_brightness(self, level=None, delta=None): raise NotImplementedError
    def wifi_list(self) -> dict: raise NotImplementedError
    def wifi_connect(self, ssid: str, password: str | None): raise NotImplementedError
    def wifi_forget(self, ssid: str): raise NotImplementedError
    def wifi_enable(self, enabled: bool): raise NotImplementedError
    def power(self, action: str): raise NotImplementedError
    def sysinfo(self) -> dict: raise NotImplementedError
    def env(self) -> dict: raise NotImplementedError
    def app_icon(self, app_id: str) -> tuple[bytes, str]: raise NotImplementedError
    def window_icon(self, xid: int) -> tuple[bytes, str]: raise NotImplementedError
    def open_app(self, name: str, page: str | None = None): raise NotImplementedError
    def run_default(self, what: str): raise NotImplementedError
    def run_command(self, command: str): raise NotImplementedError
    def open_path(self, path: str): raise NotImplementedError
    def terminal_at(self, path: str): raise NotImplementedError
    def pick_wallpaper(self): raise NotImplementedError
    def restart_shell(self): raise NotImplementedError
    def finish_setup(self): raise NotImplementedError

    # the login screen (only the greeter backend and the dev mock implement these)
    def greeter_state(self) -> dict: raise ApiError("only available on the login screen", 404)
    def greeter_login(self, user: str, password: str, session: str | None): raise ApiError("only available on the login screen", 404)
    def greeter_power(self, action: str): raise ApiError("only available on the login screen", 404)
    def _show_popup(self, popup: dict) -> None: pass
    def _hide_popup(self) -> None: pass

    # ---- shared --------------------------------------------------------------------
    def user(self) -> dict:
        name = getpass.getuser()
        full = name
        try:
            import pwd

            full = pwd.getpwnam(name).pw_gecos.split(",")[0].strip() or name
        except (ImportError, KeyError):
            pass
        return {"name": name, "fullName": full}

    def state(self) -> dict:
        return {
            "version": __version__,
            "user": self.user(),
            "hostname": socket.gethostname(),
            "settings": self.settings.snapshot(),
            "apps": self.apps(),
            "windows": self.windows(),
            "system": self.system_status(),
            "env": self.env(),
            "popup": self._popup,
        }

    def note_launch(self, app_id: str) -> None:
        """Remember an opened app for the Start menu's Recent list."""
        recent = [a for a in self.settings.get("recent") if a != app_id]
        try:
            self.update_settings({"recent": [app_id, *recent][:RECENT_LIMIT]})
        except ApiError:
            pass  # an id that fails validation is simply not remembered

    # ---- Files app: every change tells open Files windows to refresh ------------------------
    def _files_changed(self, *folders: str) -> None:
        self.bus.publish("files", folders=sorted({str(Path(f)) for f in folders if f}))

    def files_mkdir(self, parent, name):
        entry = self.files.mkdir(parent, name)
        self._files_changed(parent)
        return entry

    def files_new_file(self, parent, name):
        entry = self.files.new_file(parent, name)
        self._files_changed(parent)
        return entry

    def files_rename(self, path, name):
        entry = self.files.rename(path, name)
        self._files_changed(str(Path(path).parent))
        return entry

    def files_transfer(self, sources, dest, move):
        done = (self.files.move if move else self.files.copy)(sources, dest)
        self._files_changed(dest, *[str(Path(s).parent) for s in sources] if move else [])
        return {"entries": done}

    def files_trash(self, paths):
        count = self.files.trash_paths(paths)
        self._files_changed(*[str(Path(p).parent) for p in paths], "trash:///")
        return {"count": count}

    def files_restore(self, names):
        count = self.files.restore(names)
        self._files_changed("trash:///", str(self.files.home))
        return {"count": count}

    def files_empty_trash(self):
        count = self.files.empty_trash()
        self._files_changed("trash:///")
        return {"count": count}

    def file_raw(self, path: str) -> Path:
        """Image previews for the Files app (only image types are ever served)."""
        p = self.files.resolve(path)
        if p.suffix.lower() not in IMAGE_TYPES or not p.is_file():
            raise ApiError("not an image", 404)
        if p.stat().st_size > 40 * 1024 * 1024:
            raise ApiError("image too large to preview", 413)
        return p

    def vara_test(self) -> dict:
        reply = complete(self.vara.config.load(), [{"role": "user", "content": "Reply with just the word: ready"}], timeout=60)
        return {"ok": True, "reply": reply[:200]}

    def update_settings(self, patch: dict) -> dict:
        settings = self.settings.update(patch)
        self.bus.publish("settings", settings=settings)
        return settings

    def wallpapers(self) -> list[dict]:
        out = []
        if paths.WALLPAPER_DIR.is_dir():
            for path in sorted(paths.WALLPAPER_DIR.iterdir()):
                if path.suffix.lower() in IMAGE_TYPES:
                    out.append({
                        "id": f"builtin:{path.name}",
                        "name": WALLPAPER_NAMES.get(path.stem) or path.stem.replace("-", " ").replace("_", " ").title(),
                        "url": f"/wallpaper/builtin/{path.name}",
                    })
        return out

    def builtin_wallpaper(self, name: str) -> Path | None:
        path = paths.WALLPAPER_DIR / name
        if "/" in name or "\\" in name or name.startswith(".") or not path.is_file():
            return None
        return path

    def wallpaper_path(self) -> Path | None:
        value = self.settings.get("wallpaper")
        if value.startswith("builtin:"):
            path = self.builtin_wallpaper(value.split(":", 1)[1])
        else:
            path = Path(value) if Path(value).is_file() else None
        if path is None:  # missing file or a removed built-in: use the default, else any built-in
            default = DEFAULTS["wallpaper"].split(":", 1)[1]
            path = self.builtin_wallpaper(default)
            if path is None and (builtins := self.wallpapers()):
                path = self.builtin_wallpaper(builtins[0]["id"].split(":", 1)[1])
        return path

    def popup_request(self, view, anchor_x=None, data=None, height=None):
        """Open, switch or toggle the shell popup (start menu, quick settings, ...)."""
        if data is not None and not isinstance(data, dict):
            raise ApiError("popup data must be an object")
        with self._popup_lock:
            if view is None:
                return self._close_popup_locked()
            if view not in POPUP_SIZES:
                raise ApiError(f"unknown popup: {view}")
            key = view + json.dumps(data or {}, sort_keys=True)
            if len(key) > 4096:
                raise ApiError("popup data too large")
            if self._popup is not None and self._popup_key == key:
                return self._close_popup_locked()
            now = time.monotonic()
            if self._last_closed and self._last_closed[0] == key and now - self._last_closed[1] < REOPEN_GUARD:
                return None
            width, default_height = POPUP_SIZES[view]
            popup = {
                "view": view,
                "data": data or {},
                "width": width,
                "height": max(80, min(int(height), 900)) if height else default_height,
                "anchorX": anchor_x,
                "fullscreen": view in FULLSCREEN_POPUPS,
            }
            self._popup, self._popup_key = popup, key
        self.bus.publish("popup", popup=popup)
        self._show_popup(popup)
        return popup

    def popup_closed(self):
        with self._popup_lock:
            return self._close_popup_locked()

    def _close_popup_locked(self):
        if self._popup is None:
            return None
        self._last_closed = (self._popup_key, time.monotonic())
        self._popup = self._popup_key = None
        self.bus.publish("popup", popup=None)
        self._hide_popup()
        return None
