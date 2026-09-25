"""Simulated backend for `python main.py dev`: the whole UI in a normal browser, on any OS."""

from __future__ import annotations

import copy
import random
import shutil
import threading
import time
from pathlib import Path

from . import __version__, installer, paths, store
from .backend import DISPLAY_NAMES, DOCK_HEIGHT, DOCK_MARGIN, HIDDEN_APPS, PANEL_HEIGHT, Backend
from .core import ApiError, EventBus, Settings, letter_icon
from .files import P
from .privileged import NeedPassword

GB = 1000 ** 3
OWN_APPS = {"polyos-settings.desktop": "settings", "polyos-files.desktop": "files", "polyos-taskmgr.desktop": "taskmgr",
            "polyos-drivers.desktop": "drivers", "polyos-store.desktop": "store"}

_APPS = [
    ("firefox-esr.desktop", "Firefox ESR", "Browse the World Wide Web", "Network;WebBrowser"),
    ("polyos-files.desktop", "Files", "Browse and organize your files", "System;FileManager"),
    ("thunar.desktop", "Thunar File Manager", "Browse the filesystem", "System;FileManager"),
    ("xfce4-terminal.desktop", "Terminal", "Use the command line", "System;TerminalEmulator"),
    ("org.xfce.mousepad.desktop", "Mousepad", "Simple text editor", "Utility;TextEditor"),
    ("polyos-settings.desktop", "Settings", "Personalize and configure PolyOS", "Settings;System"),
    ("polyos-taskmgr.desktop", "Task Manager", "See and end running apps", "System;Monitor"),
    ("polyos-drivers.desktop", "Driver Manager", "Install drivers for your hardware", "System;Settings"),
    ("polyos-store.desktop", "PolyMarket", "Get trusted apps", "System;PackageManager"),
    ("pavucontrol.desktop", "Volume Control", "Adjust the volume level", "AudioVideo;Settings"),
    ("nm-connection-editor.desktop", "Advanced Network Configuration", "Manage network connections", "Settings"),
    ("htop.desktop", "Htop", "Show system processes", "System;Monitor"),
    ("org.gnome.Calculator.desktop", "Calculator", "Perform calculations", "Utility;Calculator"),
    ("libreoffice-writer.desktop", "LibreOffice Writer", "Create and edit documents", "Office"),
    ("gimp.desktop", "GNU Image Manipulation Program", "Create images and edit photographs", "Graphics"),
    ("vlc.desktop", "VLC media player", "Play movies and music", "AudioVideo"),
    ("blender.desktop", "Blender", "3D modeling, animation and rendering", "Graphics"),
    ("code.desktop", "Visual Studio Code", "Code editing. Redefined.", "Development"),
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
            ({"id": i, "name": DISPLAY_NAMES.get(i, n), "description": d, "categories": c.split(";"), "keywords": [],
              "icon": f"/icon/app/{i}", "hidden": i in HIDDEN_APPS} for i, n, d, c in apps),
            key=lambda a: a["name"].casefold())
        self._admin_ready = live  # the live USB's account needs no password; "polyos" unlocks the mock
        self._store_installed = {"firefox"}
        self._driver_state: set[str] = {"firmware-iwlwifi", "firmware-sof-signed"}
        self._procs_seed = random.Random(7)
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
        if app_id in OWN_APPS:
            return self.open_app(OWN_APPS[app_id])
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
            elif action in ("close", "kill"):
                self._windows.remove(win)
        self._publish_windows()

    def open_app(self, name, page=None):
        if name == "files":  # every call opens a new Files window, like the real shell
            self.note_launch("polyos-files.desktop")
            return self._add_window("polyos-files.desktop", "Files", page=page or P(self.files.home))
        if name == "setup":
            return self.update_settings({"setupDone": False})
        app_id = next(k for k, v in OWN_APPS.items() if v == name)
        titles = {"settings": "Settings", "taskmgr": "Task Manager", "drivers": "Driver Manager", "store": "PolyMarket"}
        if name != "settings":
            self.note_launch(app_id)
        with self._lock:
            win = next((w for w in self._windows if w["appId"] == app_id), None)
        if win is None:
            self._add_window(app_id, titles[name], page=page or ("appearance" if name == "settings" else ""))
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
        own = {"polyos-settings.desktop": "settings.svg", "polyos-files.desktop": "files.svg",
               "polyos-taskmgr.desktop": "taskmgr.svg", "polyos-drivers.desktop": "drivers.svg",
               "polyos-store.desktop": "store.svg"}
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

    # ---- administrator access (password for the mock: "polyos") ---------------------------
    def admin_status(self):
        return {"ready": self._admin_ready}

    def admin_auth(self, password):
        time.sleep(0.5)
        if password != "polyos":
            raise ApiError("That password isn't right. Try again.", 403)
        self._admin_ready = True
        return {"ready": True}

    def _simulate(self, steps, seconds, finish=None, fail=None, restart=False):
        def runner(job, update):
            for i, message in enumerate(steps):
                update({"progress": i / len(steps), "message": message})
                for _ in range(10):
                    time.sleep(seconds / len(steps) / 10)
            if fail:
                update({"error": fail})
                return 1
            if finish:
                finish()
            if restart:
                update({"restart": True})
            update({"progress": 1.0, "message": "Done."})
            return 0
        return runner

    # ---- installer --------------------------------------------------------------------
    def install_probe(self):
        if not self.live:
            raise ApiError("PolyOS is already installed on this computer.", 409)
        time.sleep(1.0)
        uefi = True
        nvme = {"path": "/dev/nvme0n1", "size": 512 * GB, "model": "Samsung SSD 970 EVO Plus", "transport": "nvme",
                "removable": False, "readonly": False, "table": "gpt", "mounts": [], "partitions": [
                    {"path": "/dev/nvme0n1p1", "number": 1, "size": 100 * 1024 ** 2, "fstype": "vfat", "label": "SYSTEM",
                     "parttype": installer.ESP_GUID.lower(), "mounts": []},
                    {"path": "/dev/nvme0n1p2", "number": 2, "size": 16 * 1024 ** 2, "fstype": "", "label": "",
                     "parttype": "e3c9e316-0b5c-4db8-817d-f92df00215ae", "mounts": []},
                    {"path": "/dev/nvme0n1p3", "number": 3, "size": 510 * GB, "fstype": "ntfs", "label": "Windows",
                     "parttype": installer.MS_BASIC_GUID.lower(), "mounts": []},
                    {"path": "/dev/nvme0n1p4", "number": 4, "size": 900 * 1024 ** 2, "fstype": "ntfs", "label": "Recovery",
                     "parttype": "de94bba4-06d1-4d40-a16a-bfd50179d6ac", "mounts": []}]}
        table = {"label": "gpt", "sector": 512, "first": 2048, "last": nvme["size"] // 512 - 34, "partitions": [
            {"node": "/dev/nvme0n1p1", "number": 1, "start": 2048, "size": 204800, "type": installer.ESP_GUID.lower()},
            {"node": "/dev/nvme0n1p2", "number": 2, "start": 206848, "size": 32768, "type": "x"},
            {"node": "/dev/nvme0n1p3", "number": 3, "start": 239616, "size": 510 * GB // 512, "type": "x"},
            {"node": "/dev/nvme0n1p4", "number": 4, "start": 239616 + 510 * GB // 512, "size": 1843200, "type": "x"}]}
        resize = {"/dev/nvme0n1p3": {"fs": "ntfs", "min": 131 * GB, "used": 131 * GB, "reason": None}}
        hdd = {"path": "/dev/sda", "size": 1000 * GB, "model": "WDC WD10SPZX", "transport": "sata", "removable": False,
               "readonly": False, "table": None, "mounts": [], "partitions": []}
        usb = {"path": "/dev/sdb", "size": 32 * GB, "model": "SanDisk Ultra", "transport": "usb", "removable": True,
               "readonly": False, "table": "dos", "mounts": [], "partitions": [
                   {"path": "/dev/sdb1", "number": 1, "size": 32 * GB, "fstype": "iso9660", "label": "PolyOS 0.2.0",
                    "parttype": "0x0", "mounts": ["/run/live/medium"]}]}
        disks = [installer.describe_disk(nvme, table, {"/dev/nvme0n1p1": "Windows 11"}, uefi, "/dev/sdb", resize),
                 installer.describe_disk(hdd, None, {}, uefi, "/dev/sdb", {}),
                 installer.describe_disk(usb, {"label": "dos", "sector": 512, "first": 0, "last": None,
                                               "partitions": []}, {}, uefi, "/dev/sdb", {})]
        return {"uefi": uefi, "secureBoot": True, "ram": 8 * 1024 ** 3, "disks": disks, "minBytes": installer.MIN_ROOT,
                "liveDisk": "/dev/sdb"}

    def install_start(self, plan):
        if not self.live:
            raise ApiError("PolyOS is already installed on this computer.", 409)
        try:
            clean = installer.validate_plan(plan)
        except installer.InstallError as exc:
            raise ApiError(str(exc)) from None
        steps = ["Preparing the disk…", "Formatting…", "Copying PolyOS to the disk… 20%", "Copying PolyOS to the disk… 55%",
                 "Copying PolyOS to the disk… 90%", "Setting up your computer…", "Creating your account…",
                 "Installing the boot loader…", "Finishing the boot menu…", "Cleaning up…"]
        if clean["mode"] == "alongside":
            steps.insert(0, "Making room: shrinking Windows 11…")
        return self.jobs.start("install", "Installing PolyOS", [], runner=self._simulate(steps, 14))

    # ---- Driver Manager ------------------------------------------------------------------
    def drivers_scan(self):
        time.sleep(0.6)
        from .drivers import recommend

        devices = [
            {"slot": "00:02.0", "className": "VGA compatible controller", "classId": "0300", "vendor": "Intel Corporation",
             "vendorId": "8086", "device": "UHD Graphics 620", "deviceId": "5917", "driver": "i915"},
            {"slot": "01:00.0", "className": "3D controller", "classId": "0302", "vendor": "NVIDIA Corporation",
             "vendorId": "10de", "device": "GP108M [GeForce MX150]", "deviceId": "1d10", "driver": "nouveau"},
            {"slot": "02:00.0", "className": "Network controller", "classId": "0280", "vendor": "Intel Corporation",
             "vendorId": "8086", "device": "Wireless 8265 / 8275", "deviceId": "24fd", "driver": "iwlwifi"},
            {"slot": "00:1f.3", "className": "Audio device", "classId": "0403", "vendor": "Intel Corporation",
             "vendorId": "8086", "device": "Sunrise Point-LP HD Audio", "deviceId": "9d71", "driver": "snd_hda_intel"},
        ]
        items = recommend(devices, "nvidia-driver", ["firmware-misc-nonfree"])
        for it in items:
            it["missing"] = [p for p in it["packages"] if p not in self._driver_state]
        self._driver_packages = {p for d in items for p in d["packages"]}
        return {"devices": items, "secureBoot": True}

    def drivers_install(self, packages):
        bad = [p for p in packages if p not in self._driver_packages]
        if bad or not packages:
            raise ApiError("Scan for drivers again, then pick from the list.")
        if not self._admin_ready:
            raise NeedPassword()

        def finish():
            self._driver_state.update(packages)
        runner = self._simulate(["Checking Debian for the latest versions…", "Downloading…", "Installing drivers…",
                                 "Configuring…"], 6, finish, restart=any(p.startswith("nvidia") for p in packages))
        return self.jobs.start("drivers", "Installing drivers", [], runner=runner,
                               on_done=lambda j: self.bus.publish("drivers"))

    # ---- PolyMarket ------------------------------------------------------------------------
    def store_list(self):
        data = store.load()
        apps = [{**a, "installed": a["id"] in self._store_installed} for a in data["apps"]]
        return {"categories": data["categories"], "apps": apps, "flatpak": True}

    def store_action(self, app_id, action):
        app = self._store_app(app_id)
        if action == "remove" and app.get("system"):
            raise ApiError(f"{app['name']} is part of PolyOS and can't be removed.")
        if not self._admin_ready:
            raise NeedPassword()

        def finish():
            desktop = (app.get("desktop") or [None])[0]
            if action == "install":
                self._store_installed.add(app_id)
                if desktop and all(a["id"] != desktop for a in self._apps):
                    self._apps.append({"id": desktop, "name": app["name"], "description": app["summary"],
                                       "categories": [], "keywords": [], "icon": f"/icon/app/{desktop}", "hidden": False})
                    self._apps.sort(key=lambda a: a["name"].casefold())
            else:
                self._store_installed.discard(app_id)
                self._apps = [a for a in self._apps if a["id"] != desktop]
            self.bus.publish("apps", apps=self._apps)
        steps = (["Checking Debian for the latest versions…", "Downloading…", f"Installing {app['name']}…"]
                 if app["source"] == "debian" else ["Connecting to Flathub…", "Downloading runtime… 35%",
                                                    f"Installing {app['name']}… 80%"])
        if action == "remove":
            steps = [f"Removing {app['name']}…"]
        verb = "Installing" if action == "install" else "Removing"
        return self.jobs.start("store", f"{verb} {app['name']}", [], target=app_id,
                               runner=self._simulate(steps, 5 if action == "install" else 2, finish),
                               on_done=lambda j: self.bus.publish("store"))

    # ---- Task Manager -----------------------------------------------------------------------
    def procs(self):
        rnd = self._procs_seed
        apps = []
        for w in self.windows():
            app = next((a for a in self._apps if a["id"] == w["appId"]), None)
            base = 420 if "firefox" in (w["appId"] or "") else 80
            apps.append({"pid": 4000 + w["xid"] % 997, "name": app["name"] if app else w["title"], "title": w["title"],
                         "icon": w["icon"], "cpu": round(rnd.uniform(0, 9 if base > 100 else 3), 1),
                         "memory": int((base + rnd.uniform(-10, 40)) * 1024 ** 2), "count": 6 if base > 100 else 1,
                         "status": "Running", "protected": False})
        names = [("pipewire-pulse", 12), ("NetworkManager applet", 22), ("xfce4-notifyd", 18), ("gvfs-udisks2-volume-monitor", 9),
                 ("tracker-miner-fs", 34), ("blueman-applet", 26), ("light-locker", 14), ("at-spi2-registryd", 6)]
        background = [{"pid": 2000 + i * 17, "name": n, "cmdline": f"/usr/bin/{n}", "cpu": round(rnd.uniform(0, 1.2), 1),
                       "memory": int((m + rnd.uniform(0, 4)) * 1024 ** 2), "count": 1, "status": "Running", "protected": False}
                      for i, (n, m) in enumerate(names)]
        desktop = [{"pid": 1200 + i, "name": n, "cmdline": n, "cpu": round(rnd.uniform(0, c), 1), "memory": int(m * 1024 ** 2),
                    "count": 1, "status": "Running", "protected": True}
                   for i, (n, c, m) in enumerate([("polyos-shell", 3, 160), ("openbox", 0.5, 18), ("picom", 2, 40),
                                                   ("Xorg", 2, 90), ("polyos-session", 0.1, 21)])]
        cpu = round(min(100, sum(a["cpu"] for a in apps + background + desktop) + rnd.uniform(2, 6)), 1)
        return {"apps": sorted(apps, key=lambda r: -r["cpu"]), "background": sorted(background, key=lambda r: -r["cpu"]),
                "desktop": desktop,
                "perf": {"cpu": cpu, "cores": [round(max(0, min(100, cpu + rnd.uniform(-8, 8))), 1) for _ in range(4)],
                         "cpuModel": "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz", "memTotal": 8 * 1024 ** 3,
                         "memUsed": int((2.6 + len(apps) * 0.35 + rnd.uniform(0, 0.2)) * 1024 ** 3),
                         "memCached": int(1.4 * 1024 ** 3), "swapTotal": 4 * 1024 ** 3, "swapUsed": 0,
                         "processes": 180 + len(apps) * 6, "threads": 920, "uptime": int(time.monotonic()) % 86400,
                         "netDown": int(rnd.uniform(0, 400_000)), "netUp": int(rnd.uniform(0, 60_000)),
                         "diskRead": int(rnd.uniform(0, 2_000_000)), "diskWrite": int(rnd.uniform(0, 800_000))}}

    def procs_end(self, pid, force):
        with self._lock:
            win = next((w for w in self._windows if 4000 + w["xid"] % 997 == pid), None)
        if win is not None:
            return self.window_action(win["xid"], "close")
        if 1200 <= pid < 1300:
            raise ApiError("That's part of PolyOS itself and can't be ended here.", 403)


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
