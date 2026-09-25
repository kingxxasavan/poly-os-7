"""The backend contract the web UI talks to, plus logic shared by every backend."""

from __future__ import annotations

import getpass
import json
import os
import socket
import threading
import time
from pathlib import Path

from . import __version__, devmode, drivers, gaming, paths, security, store
from .core import DEFAULTS, IMAGE_TYPES, ApiError, EventBus, Settings, bundled_icon, letter_icon, log
from .files import FileSystem
from .privileged import Jobs
from .vara import Vara, complete
from .widgets import Widgets

# Floating dock geometry in logical px. The dock window is the bar itself, inset from the
# screen edges; openbox keeps PANEL_HEIGHT (times the UI scale) free for maximized windows.
DOCK_HEIGHT = 52
DOCK_MARGIN = 8
PANEL_HEIGHT = DOCK_HEIGHT + DOCK_MARGIN + 4

# Popup sizes in logical px. "taskmenu" height is supplied by the panel (it depends on the items).
# Full-screen popups cover the monitor above the dock; their size is filled in by the shell.
FULLSCREEN_POPUPS = {"launcher", "power"}
TALL_POPUPS = {"widgets"}  # full height at the left edge, like the Windows widgets board
POPUP_SIZES = {
    "start": (400, 596),  # the PolyOS Home Menu
    "launcher": (0, 0),
    "power": (0, 0),
    "run": (460, 188),
    "vara": (480, 680),
    "quick": (360, 326),  # the Wi-Fi list asks for more height via the "height" field
    "calendar": (320, 390),
    "taskmenu": (240, 200),
    "quickmenu": (264, 468),  # Super+X: the Windows-style quick link menu
    "widgets": (760, 0),
}
RECENT_LIMIT = 6
WALLPAPER_NAMES = {"polyos-prism": "Crystal", "polyos-amethyst": "Amethyst", "polyos-dusk": "Dusk",
                   "polyos-violet": "Violet", "polyos-night": "Night", "polyos-crystal": "Facets", "pixapoly": "PIXAPoLY"}
# Built-ins listed first in Settings, in this order; the rest follow alphabetically.
WALLPAPER_ORDER = ("polyos-prism", "polyos-amethyst")
POWER_ACTIONS = ("lock", "logout", "suspend", "reboot", "poweroff")
RUN_TARGETS = ("terminal", "files", "browser")
OPEN_APPS = ("settings", "files", "setup", "taskmgr", "drivers", "store", "camera")
CAMERA_APP = "polyos-camera.desktop"  # listed only when a webcam is connected
CAMERA_TYPES = {"photo": {"image/jpeg": ".jpg", "image/png": ".png"},
                "video": {"video/webm": ".webm", "video/mp4": ".mp4"}}
CAMERA_MAX_BYTES = {"photo": 30 * 1024 * 1024, "video": 1024 * 1024 * 1024}
# Launcher entries most people never need (Settings > Apps shows them again).
HIDDEN_APPS = {
    "thunar.desktop", "thunar-bulk-rename.desktop", "thunar-settings.desktop", "thunar-volman-settings.desktop",
    "org.xfce.thunar.desktop", "pavucontrol.desktop", "org.pulseaudio.pavucontrol.desktop", "arandr.desktop",
    "nm-connection-editor.desktop", "light-locker-settings.desktop", "xfce4-notifyd-config.desktop",
    "org.xfce.xfce4-notifyd-config.desktop", "im-config.desktop", "calamares.desktop", "install-debian.desktop",
    "vim.desktop", "htop.desktop", "debian-xterm.desktop", "debian-uxterm.desktop", "xterm.desktop",
    "uxterm.desktop", "display-im6.q16.desktop", "display-im7.q16.desktop", "yelp.desktop", "obconf.desktop",
    "lightdm-gtk-greeter-settings.desktop", "blueman-adapters.desktop", "org.freedesktop.IBus.Setup.desktop",
    "ibus-setup.desktop", "qv4l2.desktop", "qvidcap.desktop", "org.gnome.FileRoller.desktop",
    "org.xfce.mousepad-settings.desktop", "xfce4-terminal-settings.desktop", "lxpolkit.desktop", "picom.desktop",
    "compton.desktop", "openbox.desktop", "debian-reference-common.desktop", "python3.13.desktop",
    "python3.11.desktop", "nvidia-settings.desktop", "org.gnome.Evince-previewer.desktop", "polyos-setup.desktop",
    "info.desktop", "bssh.desktop", "bvnc.desktop", "avahi-discover.desktop", "jconsole.desktop",
    "policytool.desktop", "gcr-prompter.desktop", "gcr-viewer.desktop", "org.gnome.seahorse.Application.desktop",
    "firefox-esr-safe.desktop", "nm-applet.desktop", "xfce4-about.desktop", "org.xfce.volman.desktop",
}
# Friendlier names for Debian's default apps.
DISPLAY_NAMES = {
    "firefox-esr.desktop": "Firefox", "org.xfce.mousepad.desktop": "Text Editor", "xfce4-terminal.desktop": "Terminal",
    "org.xfce.ristretto.desktop": "Image Viewer", "xfce4-screenshooter.desktop": "Screenshot",
    "blueman-manager.desktop": "Bluetooth", "org.gnome.Evince.desktop": "Documents",
}
# Clicking the button that opened a popup first blurs it (closing it) and then
# toggles it again; ignore a reopen of the same popup this soon after a close.
REOPEN_GUARD = 0.35


def panel_margin(settings: dict) -> int:
    """Logical px openbox keeps free at the bottom for maximized windows."""
    if settings.get("taskbarAutoHide"):
        return 0  # maximized windows fill the screen; the taskbar slides over them
    return DOCK_HEIGHT if settings.get("taskbarStyle") == "full" else PANEL_HEIGHT


def dock_geometry(settings: dict, width: int, height: int) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the taskbar on a monitor of this size (monitor-relative)."""
    if settings.get("taskbarStyle") == "full":
        return 0, height - DOCK_HEIGHT, width, DOCK_HEIGHT
    return DOCK_MARGIN, height - DOCK_MARGIN - DOCK_HEIGHT, width - 2 * DOCK_MARGIN, DOCK_HEIGHT


class Backend:
    """Subclasses: MockBackend (dev in a browser) and DesktopShell (the real session)."""

    dev = False

    def __init__(self, settings: Settings, bus: EventBus, home: Path | None = None):
        self.settings = settings
        self.bus = bus
        self.files = FileSystem(home or Path.home())
        self.vara = Vara(settings.path.parent / "vara.json", bus, self.files.home)  # ~/.config/polyos/vara.json
        self.vara.on_attention = self._vara_attention
        self.jobs = Jobs(bus)
        self._driver_packages: set[str] = set()
        self.widgets = Widgets(settings.path.parent / "widgets.json", self.files.home)
        self._popup_lock = threading.Lock()
        self._popup: dict | None = None
        self._popup_key: str | None = None
        self._last_closed: tuple[str, float] | None = None
        self.unlock_throttle = security.Throttle()

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
    def theme_icon(self, name: str) -> tuple[bytes, str]:
        names = [n for n in name.split(",") if n][:6]
        icon = bundled_icon(names)
        if icon:
            return icon, "image/svg+xml"
        return letter_icon((names[0] if names else "?").split(".")[-1] or "?"), "image/svg+xml"

    def lock(self): raise ApiError("locking isn't available here", 404)
    def lock_unlock(self, password: str): raise ApiError("locking isn't available here", 404)
    def lock_recover(self, key: str, password: str): raise ApiError("locking isn't available here", 404)
    def greeter_recover(self, user: str, key: str, password: str): raise ApiError("only available on the login screen", 404)
    def procs(self) -> dict: raise NotImplementedError
    def procs_end(self, pid: int, force: bool): raise NotImplementedError
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
        if full.lower() in ("debian live user", "live user"):  # the live USB's account
            full = ""
        return {"name": name, "fullName": full or name.capitalize()}

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
        if not self.settings.get("keepRecent"):
            return
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

    # ---- administrator access and background jobs ----------------------------------------
    def admin_status(self) -> dict:
        return {"ready": self.jobs.admin.ready()}

    def admin_auth(self, password: str):
        self.jobs.admin.authenticate(password)
        return {"ready": True}

    # ---- installer (live USB only) -----------------------------------------------------
    def install_probe(self) -> dict:
        if not self.env()["live"]:
            raise ApiError("PolyOS is already installed on this computer.", 409)
        return self.jobs.admin.call(["probe"], timeout=600)

    def install_start(self, plan: dict) -> dict:
        if not self.env()["live"]:
            raise ApiError("PolyOS is already installed on this computer.", 409)
        from .installer import InstallError, validate_plan

        try:
            clean = validate_plan(plan)
        except InstallError as exc:
            raise ApiError(str(exc)) from None
        path = paths.runtime_dir() / "install-plan.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(clean, fh)
        return self.jobs.start("install", "Installing PolyOS", ["install", str(path)])

    def install_restart(self):
        """Restart right away after installing (a normal restart waits on the live system's services)."""
        if not self.env()["live"]:
            raise ApiError("PolyOS is already installed on this computer.", 409)
        self.jobs.admin.stream(["reboot"], lambda _event: None)

    # ---- your account -------------------------------------------------------------------
    def _account_request(self, payload: dict) -> None:
        path = paths.runtime_dir() / "account-request.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        errors: list[str] = []
        rc = self.jobs.admin.stream(["account", str(path)], lambda e: errors.append(e["error"]) if "error" in e else None)
        path.unlink(missing_ok=True)
        if errors or rc != 0:
            raise ApiError(errors[-1] if errors else "That didn't work. Try again.", 500)

    def account_password(self, current: str, password: str):
        if not password or len(password) > 256 or "\n" in password:
            raise ApiError("Choose a new password.")
        self.jobs.admin.authenticate(current)  # proves it's you (and unlocks sudo)
        self._account_request({"password": password})
        return {"ok": True}

    def account_recovery_key(self):
        from .recovery import generate

        if not self.jobs.admin.ready():
            from .privileged import NeedPassword

            raise NeedPassword()
        key = generate()
        self._account_request({"recoveryKey": key})
        return {"key": key}

    # ---- Driver Manager ------------------------------------------------------------------
    def drivers_scan(self) -> dict:
        result = drivers.scan()
        self._driver_packages = {p for d in result["devices"] for p in d["packages"]}
        return result

    def drivers_install(self, packages: list[str]) -> dict:
        bad = [p for p in packages if p not in self._driver_packages or not drivers.DRIVER_PACKAGE_RE.match(p)]
        if bad or not packages:
            raise ApiError("Scan for drivers again, then pick from the list.")
        return self.jobs.start("drivers", "Installing drivers", ["drivers", *packages],
                               on_done=lambda job: self.bus.publish("drivers"))

    # ---- PolyMarket ------------------------------------------------------------------------
    def _store_app(self, app_id: str) -> dict:
        app = store.validate(store.load()).get(app_id)
        if app is None:
            raise ApiError("That app isn't in PolyMarket.", 404)
        return app

    def store_list(self) -> dict:
        return store.catalog_with_status(store.load())

    def store_action(self, app_id: str, action: str) -> dict:
        app = self._store_app(app_id)
        if action == "remove" and app.get("system"):
            raise ApiError(f"{app['name']} is part of PolyOS and can't be removed.")
        verb = "Installing" if action == "install" else "Removing"
        return self.jobs.start("store", f"{verb} {app['name']}", ["store", action, app_id], target=app_id,
                               on_done=lambda job: self.bus.publish("store"))

    def store_open(self, app_id: str):
        app = self._store_app(app_id)
        ids = {a["id"] for a in self.apps()}
        target = next((d for d in app.get("desktop", []) if d in ids), None)
        if target is None:
            raise ApiError(f"{app['name']} runs from the Terminal." if not app.get("desktop") else
                           f"{app['name']} isn't installed yet.", 404)
        return self.launch(target)

    def performance(self) -> dict:
        """The login and lock screens' "Performance: Optimal" card (load average and free memory)."""
        try:
            load = os.getloadavg()[0] / (os.cpu_count() or 1)
        except (AttributeError, OSError):
            return {"level": "optimal"}
        avail = 1.0
        try:
            info = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    info[key] = int(rest.split()[0])
            avail = info["MemAvailable"] / info["MemTotal"]
        except (OSError, KeyError, ValueError, IndexError, ZeroDivisionError):
            pass
        level = "optimal" if load < 0.7 and avail > 0.15 else "busy" if load < 1.5 and avail > 0.05 else "high"
        return {"level": level, "load": round(load, 2), "memoryFree": round(avail, 2)}

    def power_modes(self) -> dict:
        """Settings > Power: the four PolyOS modes and whether this computer can switch profiles."""
        from .power import MODE_INFO, available_profiles

        offered = available_profiles()
        return {"modes": [{"id": k, "name": v[0], "description": v[1]} for k, v in MODE_INFO.items()],
                "profiles": offered, "switchable": bool(offered)}

    # ---- Camera app ----------------------------------------------------------------------
    def has_camera(self) -> bool:
        from .power import has_camera

        return has_camera()

    def camera_status(self) -> dict:
        folder = self.files.home / "Pictures" / "Camera"
        return {"camera": self.has_camera(), "allowed": self.settings.get("cameraAccess"),
                "micAllowed": self.settings.get("micAccess"), "folder": str(folder)}

    def camera_save(self, kind: str, ctype: str, data: bytes) -> dict:
        """Save a photo or video from the Camera app to ~/Pictures/Camera."""
        if not self.settings.get("cameraAccess"):
            raise ApiError("Camera access is turned off in Settings > Privacy & security.", 403)
        ext = CAMERA_TYPES.get(kind, {}).get(ctype.split(";")[0].strip().lower())
        if ext is None:
            raise ApiError("unsupported photo or video format", 415)
        if not data:
            raise ApiError("nothing was captured")
        if kind == "photo" and not (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG")):
            raise ApiError("that isn't a photo", 415)
        folder = self.files.home / "Pictures" / "Camera"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        prefix = "Photo" if kind == "photo" else "Video"
        for n in range(100):
            target = folder / f"{prefix} {stamp}{f' ({n + 1})' if n else ''}{ext}"
            try:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                break
            except FileExistsError:
                continue
        else:
            raise ApiError("couldn't pick a file name", 500)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        self._files_changed(str(folder))
        return {"path": str(target), "name": target.name}

    # ---- editions: Gaming and Developer packs ----------------------------------------------
    def packs(self) -> dict:
        return {"packs": store.packs_with_status(store.load()), "edition": self.settings.get("edition")}

    def pack_install(self, name: str, ids: list[str]) -> dict:
        info = store.pack(store.load(), name)
        if info is None:
            raise ApiError("That edition doesn't exist.", 404)
        allowed = {aid for aid, _default in info["apps"]}
        if not ids or any(i not in allowed for i in ids):
            raise ApiError(f"Pick apps from the {info['name']} list.")

        def done(job):
            self.bus.publish("store")
            if job["state"] == "done":
                self.update_settings({"editionSetup": True})
        return self.jobs.start("pack", f"Setting up {info['name']}", ["pack", name, *ids], target=name, on_done=done)

    # ---- cloud gaming ------------------------------------------------------------------------
    def cloud_gaming(self) -> dict:
        return {"services": [{"id": cid, "name": v[0], "url": v[1], "summary": v[2]} for cid, v in gaming.CLOUD.items()],
                "installed": gaming.installed(self.files.home)}

    def cloud_gaming_set(self, ids: list[str]) -> dict:
        if any(i not in gaming.CLOUD for i in ids):
            raise ApiError("Unknown cloud gaming service.")
        gaming.set_shortcuts(self.files.home, ids)
        self._apps_changed()
        return self.cloud_gaming()

    def _apps_changed(self) -> None:
        """New .desktop files (the real shell notices them itself)."""

    # ---- security checkup --------------------------------------------------------------------
    def security_status(self) -> dict:
        from . import recovery

        status = security.status()
        try:
            # the records folder is root-only on most systems: then it can't be checked from here
            status["recoveryKey"] = recovery.has_key(self.user()["name"]) if os.access(recovery.STORE, os.X_OK) else None
        except Exception:  # noqa: BLE001 - unreadable record: just don't claim one
            status["recoveryKey"] = None
        status["lockOnSleep"] = self.settings.get("lockOnSleep")
        return status

    def security_set(self, what: str, on: bool) -> dict:
        if what not in ("firewall", "updates"):
            raise ApiError("Unknown security setting.")
        title = {"firewall": "Firewall", "updates": "Automatic updates"}[what]
        return self.jobs.start("security", f"{title} {'on' if on else 'off'}", ["security", what, "on" if on else "off"],
                               target=what, on_done=lambda _job: self.bus.publish("security"))

    # ---- developer mode ----------------------------------------------------------------------
    def ui_override(self, rel: str) -> Path | None:
        """A developer's replacement for a built-in UI file (only while developer mode is on)."""
        if not self.settings.get("developerMode"):
            return None
        return devmode.resolve(self.settings.path.parent, rel)

    def dev_action(self, action: str) -> dict:
        config = self.settings.path.parent
        if action == "folder":
            path = devmode.prepare(config)
        elif action == "source":
            path = devmode.copy_source(paths.UI_DIR, self.files.home)
        elif action == "reset":
            aside = devmode.reset(config)
            return {"path": str(aside) if aside else None}
        else:
            raise ApiError("Unknown developer action.")
        self.open_app("files", str(path))
        return {"path": str(path)}

    def widgets_update(self, patch: dict) -> dict:
        data = self.widgets.update(patch)
        self.bus.publish("widgets", keys=sorted(patch))
        return data

    def _vara_attention(self) -> None:
        """Vara is waiting for an Allow or Deny: bring its chat back if no popup is open."""
        with self._popup_lock:
            busy_elsewhere = self._popup is not None
        if not busy_elsewhere:
            try:
                self.popup_request("vara")
            except Exception:  # noqa: BLE001 - the chat still shows the request when opened
                log.debug("couldn't open Vara for an approval", exc_info=True)

    def vara_test(self) -> dict:
        reply = complete(self.vara.config.load(), [{"role": "user", "content": "Reply with just the word: ready"}], timeout=60)
        return {"ok": True, "reply": reply[:200]}

    def update_settings(self, patch: dict) -> dict:
        if isinstance(patch, dict) and patch.get("keepRecent") is False:
            patch = {**patch, "recent": []}  # turning activity history off forgets it too
        settings = self.settings.update(patch)
        self.bus.publish("settings", settings=settings)
        return settings

    def wallpapers(self) -> list[dict]:
        out = []
        if paths.WALLPAPER_DIR.is_dir():
            rank = {stem: i for i, stem in enumerate(WALLPAPER_ORDER)}
            for path in sorted(paths.WALLPAPER_DIR.iterdir(), key=lambda p: (rank.get(p.stem, len(rank)), p.name)):
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

    def wallpaper_path(self, key: str = "wallpaper") -> Path | None:
        value = self.settings.get(key)
        if value.startswith("builtin:"):
            path = self.builtin_wallpaper(value.split(":", 1)[1])
        else:
            path = Path(value) if Path(value).is_file() else None
        if path is None:  # missing file or a removed built-in: use the default, else any built-in
            default = DEFAULTS[key].split(":", 1)[1]
            path = self.builtin_wallpaper(default)
            if path is None and (builtins := self.wallpapers()):
                path = self.builtin_wallpaper(builtins[0]["id"].split(":", 1)[1])
        return path

    def popup_request(self, view, anchor_x=None, data=None, height=None, toggle_any=False):
        """Open, switch or toggle the shell popup (start menu, quick settings, ...).

        toggle_any (the Windows key): close whatever popup is open instead of switching to `view`.
        """
        if data is not None and not isinstance(data, dict):
            raise ApiError("popup data must be an object")
        with self._popup_lock:
            if view is None or (toggle_any and self._popup is not None):
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
                "tall": view in TALL_POPUPS,
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
