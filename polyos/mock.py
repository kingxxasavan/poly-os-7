"""Simulated backend for `python main.py dev`: the whole UI in a normal browser, on any OS."""

from __future__ import annotations

import copy
import shutil
import threading
import time
from pathlib import Path

from . import __version__, paths
from .backend import DOCK_HEIGHT, DOCK_MARGIN, PANEL_HEIGHT, Backend
from .core import ApiError, EventBus, Settings, letter_icon
from .files import P

_APPS = [
    ("firefox-esr.desktop", "Firefox ESR", "Browse the World Wide Web", "Network;WebBrowser"),
    ("polyos-files.desktop", "Files", "Browse and organize your files", "System;FileManager"),
    ("thunar.desktop", "Thunar File Manager", "Browse the filesystem", "System;FileManager"),
    ("xfce4-terminal.desktop", "Terminal", "Use the command line", "System;TerminalEmulator"),
    ("org.xfce.mousepad.desktop", "Mousepad", "Simple text editor", "Utility;TextEditor"),
    ("polyos-settings.desktop", "Settings", "Personalize and configure PolyOS", "Settings;System"),
    ("org.gnome.Calculator.desktop", "Calculator", "Perform calculations", "Utility;Calculator"),
    ("libreoffice-writer.desktop", "LibreOffice Writer", "Create and edit documents", "Office"),
    ("gimp.desktop", "GNU Image Manipulation Program", "Create images and edit photographs", "Graphics"),
    ("vlc.desktop", "VLC media player", "Play movies and music", "AudioVideo"),
    ("blender.desktop", "Blender", "3D modeling, animation and rendering", "Graphics"),
    ("code.desktop", "Visual Studio Code", "Code editing. Redefined.", "Development"),
    ("pavucontrol.desktop", "Volume Control", "Adjust the volume level", "AudioVideo;Settings"),
    ("arandr.desktop", "ARandR", "Arrange displays", "Settings"),
    ("xfce4-screenshooter.desktop", "Screenshot", "Take screenshots", "Utility"),
    ("org.xfce.ristretto.desktop", "Ristretto Image Viewer", "Look at your images", "Graphics"),
    ("steam.desktop", "Steam", "Application for managing and playing games", "Game"),
]


class MockBackend(Backend):
    dev = True

    def __init__(self, settings: Settings, bus: EventBus, live: bool = False, home: Path | None = None):
        home = Path(home) if home else paths.ROOT / "build" / "dev-home"
        seed_home(home)
        super().__init__(settings, bus, home=home)
        self.live = live
        self._lock = threading.Lock()
        apps = list(_APPS)
        if live:
            apps.append(("install-debian.desktop", "Install PolyOS", "Install to this computer", "System"))
        self._apps = sorted(
            ({"id": i, "name": n, "description": d, "categories": c.split(";"), "keywords": [],
              "icon": f"/icon/app/{i}"} for i, n, d, c in apps),
            key=lambda a: a["name"].casefold())
        self._windows: list[dict] = []
        self._next_xid = 0x3a00001
        self._system = {
            "volume": {"available": True, "level": 45, "muted": False},
            "brightness": {"available": True, "level": 70},
            "battery": {"present": True, "level": 76, "charging": False, "plugged": False},
            "network": {"available": True, "kind": "wifi", "name": "PolyNet", "signal": 78,
                        "wifiDevice": "wlan0", "wifiEnabled": True},
        }
        self._wifi = [
            {"ssid": "PolyNet", "signal": 78, "security": "WPA2", "secure": True, "active": True, "known": True},
            {"ssid": "Library Guest", "signal": 64, "security": "", "secure": False, "active": False, "known": False},
            {"ssid": "Panthers-5G", "signal": 52, "security": "WPA2 WPA3", "secure": True, "active": False, "known": False},
            {"ssid": "DIRECT-roku-219", "signal": 31, "security": "WPA2", "secure": True, "active": False, "known": False},
        ]

    # ---- apps and windows ------------------------------------------------------------
    def apps(self):
        return self._apps

    def windows(self):
        with self._lock:
            return copy.deepcopy(self._windows)

    def _publish_windows(self):
        self.bus.publish("windows", windows=self.windows())

    def _app(self, app_id):
        app = next((a for a in self._apps if a["id"] == app_id), None)
        if app is None:
            raise ApiError("app not found", 404)
        return app

    def launch(self, app_id):
        if app_id == "polyos-settings.desktop":
            return self.open_app("settings")
        if app_id == "polyos-files.desktop":
            return self.open_app("files")
        app = self._app(app_id)
        self.note_launch(app_id)
        self._add_window(app["id"], app["name"])

    def _add_window(self, app_id, title, **extra):
        with self._lock:
            for w in self._windows:
                w["active"] = False
            xid, self._next_xid = self._next_xid, self._next_xid + 0x100
            self._windows.append({"xid": xid, "title": title, "appId": app_id, "active": True,
                                  "minimized": False, "icon": f"/icon/app/{app_id}", **extra})
        self.popup_closed()
        self._publish_windows()

    def window_action(self, xid, action):
        with self._lock:
            win = next((w for w in self._windows if w["xid"] == xid), None)
            if win is None:
                raise ApiError("window not found", 404)
            if action == "toggle":
                action = "minimize" if win["active"] and not win["minimized"] else "activate"
            if action == "activate":
                for w in self._windows:
                    w["active"] = w is win
                win["minimized"] = False
            elif action == "minimize":
                win.update(minimized=True, active=False)
            elif action == "close":
                self._windows.remove(win)
        self._publish_windows()

    def open_app(self, name, page=None):
        if name == "files":  # every call opens a new Files window, like the real shell
            self.note_launch("polyos-files.desktop")
            return self._add_window("polyos-files.desktop", "Files", page=page or P(self.files.home))
        if name == "setup":
            return self.update_settings({"setupDone": False})
        with self._lock:
            win = next((w for w in self._windows if w["appId"] == "polyos-settings.desktop"), None)
        if win is None:
            self._add_window("polyos-settings.desktop", "Settings", page=page or "appearance")
        else:
            self.window_action(win["xid"], "activate")
            if page:
                self.bus.publish("navigate", surface="settings", page=page)

    def finish_setup(self):
        self.update_settings({"setupDone": True})

    # ---- login screen (password for every mock account: "polyos") ------------------------
    def greeter_state(self):
        user = self.user()
        return {
            "users": [{"name": user["name"], "displayName": user["fullName"], "loggedIn": False},
                      {"name": "andrew", "displayName": "Andrew", "loggedIn": False}],
            "sessions": [{"key": "polyos", "name": "PolyOS"}, {"key": "xfce", "name": "Xfce Session"}],
            "defaultSession": "polyos", "selectedUser": user["name"], "lock": self.greeter_lock,
            "hideUsers": False, "hostname": "polyos",
            "can": {"shutdown": True, "restart": True, "suspend": True},
        }

    greeter_lock = False

    def greeter_login(self, user, password, session):
        time.sleep(0.6)
        if password != "polyos":
            raise ApiError("The password entered is incorrect. Please try again.", 403)
        self.bus.publish("power", action="login")
        return {"ok": True}

    def greeter_power(self, action):
        self.bus.publish("power", action={"shutdown": "poweroff", "restart": "reboot"}.get(action, action))

    def open_path(self, path):
        p = self.files.resolve(path)
        if p.is_dir():
            return self.open_app("files", str(p))
        kind = self.files.entry(p)["kind"]
        app = {"image": "org.xfce.ristretto.desktop", "video": "vlc.desktop", "audio": "vlc.desktop"}.get(kind, "org.xfce.mousepad.desktop")
        self._add_window(app, p.name)

    def terminal_at(self, path):
        self.launch("xfce4-terminal.desktop")

    def run_default(self, what):
        if what == "files":
            return self.open_app("files")
        category = {"terminal": "TerminalEmulator", "files": "FileManager", "browser": "WebBrowser"}[what]
        app = next(a for a in self._apps if category in a["categories"])
        self.launch(app["id"])

    def run_command(self, command):
        name = command.strip().split()[0] if command.strip() else ""
        if not name:
            raise RuntimeError("Type a command to run")
        match = next((a for a in self._apps if a["id"].split(".")[-2].endswith(name.lower())
                      or a["name"].lower().startswith(name.lower())), None)
        if match is None:
            raise RuntimeError(f"PolyOS can't find “{name}”")
        self.launch(match["id"])

    def app_icon(self, app_id):
        own = {"polyos-settings.desktop": "settings.svg", "polyos-files.desktop": "files.svg"}
        if app_id in own:
            return (paths.UI_DIR / "img" / own[app_id]).read_bytes(), "image/svg+xml"
        name = next((a["name"] for a in self._apps if a["id"] == app_id), app_id)
        return letter_icon(name), "image/svg+xml"

    def window_icon(self, xid):
        return letter_icon("?"), "image/svg+xml"

    # ---- system --------------------------------------------------------------------------
    def system_status(self):
        with self._lock:
            return copy.deepcopy(self._system)

    def _publish_system(self):
        self.bus.publish("system", system=self.system_status())
        return self.system_status()

    def set_volume(self, level=None, delta=None, muted=None, toggle_mute=False):
        with self._lock:
            vol = self._system["volume"]
            if delta is not None:
                level = vol["level"] + delta
            if level is not None:
                vol["level"] = max(0, min(100, level))
                if muted is None and not toggle_mute and vol["level"] > 0:
                    vol["muted"] = False
            if toggle_mute:
                vol["muted"] = not vol["muted"]
            elif muted is not None:
                vol["muted"] = muted
        return self._publish_system()["volume"]

    def set_brightness(self, level=None, delta=None):
        with self._lock:
            bl = self._system["brightness"]
            if delta is not None:
                level = bl["level"] + delta
            bl["level"] = max(5, min(100, level if level is not None else 100))
        return self._publish_system()["brightness"]

    def wifi_list(self):
        time.sleep(0.5)
        with self._lock:
            return {"enabled": self._system["network"]["wifiEnabled"], "networks": copy.deepcopy(self._wifi)}

    def wifi_connect(self, ssid, password):
        time.sleep(1.2)
        with self._lock:
            net = next((n for n in self._wifi if n["ssid"] == ssid), None)
            if net is None:
                raise RuntimeError("Network not found")
            if net["secure"] and not net["known"]:
                if not password:
                    raise RuntimeError("This network needs a password")
                if password == "wrong" or len(password) < 8:
                    raise RuntimeError("Could not connect. Check the password and try again.")
            for n in self._wifi:
                n["active"] = n is net
            net["known"] = True
            self._system["network"].update(kind="wifi", name=ssid, signal=net["signal"])
        self._publish_system()

    def wifi_forget(self, ssid):
        with self._lock:
            for n in self._wifi:
                if n["ssid"] == ssid:
                    n["known"] = False
                    if n["active"]:
                        n["active"] = False
                        self._system["network"].update(kind="none", name=None, signal=None)
        self._publish_system()

    def wifi_enable(self, enabled):
        with self._lock:
            net = self._system["network"]
            net["wifiEnabled"] = enabled
            if not enabled:
                net.update(kind="none", name=None, signal=None)
                for n in self._wifi:
                    n["active"] = False
        self._publish_system()

    def power(self, action):
        self.popup_closed()
        self.bus.publish("power", action=action)

    def sysinfo(self):
        return {"os": "Debian GNU/Linux 13 (trixie)", "kernel": "6.12.41-amd64", "arch": "x86_64",
                "cpu": "Intel(R) Core(TM) i5-6300U CPU @ 2.40GHz", "cores": 4,
                "memoryBytes": 8 * 1024 ** 3, "diskTotal": 128 * 1000 ** 3, "diskFree": 81 * 1000 ** 3,
                "uptime": 3 * 3600 + 17 * 60, "hostname": "polyos"}

    def env(self):
        return {"dev": True, "composited": True, "live": self.live,
                "installer": "install-debian.desktop" if self.live else None,
                "panelHeight": PANEL_HEIGHT, "dockHeight": DOCK_HEIGHT,
                "dockMargin": DOCK_MARGIN, "version": __version__}

    def pick_wallpaper(self):
        raise ApiError("The file picker only works on a real PolyOS session", 501)

    def restart_shell(self):
        self.bus.publish("power", action="restart-shell")


def seed_home(home: Path) -> None:
    """A small sandbox home folder for the Files app in dev mode."""
    if (home / ".seeded").exists():
        return
    samples = {
        "Documents/Welcome to PolyOS.txt": "Everything in this folder is a sandbox for `python main.py dev`.\n",
        "Documents/School/Chemistry notes.md": "# Chemistry\n\n- Stoichiometry\n- Gas laws\n",
        "Documents/School/History essay.docx": "",
        "Documents/Budget.xlsx": "",
        "Documents/Launch deck.pptx": "",
        "Downloads/polyos-0.1.0-trixie-amd64.iso": "",
        "Downloads/scratch-project.sb3": "",
        "Downloads/report.pdf": "%PDF-1.4\n",
        "Downloads/archive.tar.gz": "",
        "Music/Lo-fi mix.mp3": "",
        "Videos/Launch trailer.mp4": "",
        "Desktop/Ideas.txt": "PolyOS ideas\n",
        "Projects/jarvis/jarvis.py": "print('hello from JARVIS')\n",
        ".bashrc": "# hidden file\n",
    }
    for rel, text in samples.items():
        target = home / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, "utf-8")
    (home / "Pictures").mkdir(parents=True, exist_ok=True)
    for name in ("polyos-dusk.jpg", "polyos-violet.jpg", "pixapoly.jpg"):
        src = paths.WALLPAPER_DIR / name
        if src.exists():
            shutil.copy(src, home / "Pictures" / name)
    (home / ".seeded").write_text("1")
