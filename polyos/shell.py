"""The PolyOS desktop shell: desktop, taskbar and popup surfaces on X11.

Each surface is an undecorated GTK window hosting a WebKit view of the web UI. The
window manager (openbox) handles app windows; this process tracks them with libwnck,
lists apps from .desktop files with Gio, and serves the UI through polyos.server.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("GDK_BACKEND", "x11")  # wnck and window type hints need X11
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")  # avoids blank views on some GPUs/VMs

import gi  # noqa: E402

gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Wnck", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, GdkPixbuf, GdkX11, Gio, GLib, Gtk, WebKit2, Wnck  # noqa: E402

from . import __version__, paths, system, theme  # noqa: E402
from .backend import DISPLAY_NAMES, DOCK_HEIGHT, DOCK_MARGIN, HIDDEN_APPS, PANEL_HEIGHT, Backend  # noqa: E402
from .core import IMAGE_TYPES, ApiError, EventBus, Settings, letter_icon  # noqa: E402
from .mainloop import on_main  # noqa: E402
from .procs import ProcessMonitor, protected_pids  # noqa: E402
from .server import Server  # noqa: E402

log = logging.getLogger("polyos.shell")

EXIT_LOGOUT, EXIT_RESTART = 0, 3
SOLID_BG = "#151515"
# PolyOS's own apps: launching their .desktop entries opens them in the shell directly.
OWN_APPS = {"polyos-settings.desktop": "settings", "polyos-files.desktop": "files", "polyos-taskmgr.desktop": "taskmgr",
            "polyos-drivers.desktop": "drivers", "polyos-store.desktop": "store"}
# name: (surface, window title, WM class, default size)
SINGLE_WINDOWS = {
    "taskmgr": ("taskmgr", "Task Manager", "polyos-taskmgr", (940, 640)),
    "drivers": ("drivers", "Driver Manager", "polyos-drivers", (900, 640)),
    "store": ("store", "PolyMarket", "polyos-store", (1120, 740)),
}
GENERIC_EXECUTABLES = {"sh", "bash", "env", "flatpak", "snap", "python3", "python", "java", "wine",
                       "exo-open", "xdg-open", "pkexec", "sudo", "gtk-launch", "polyos-ctl"}


class DesktopShell(Backend):
    def __init__(self, settings: Settings, bus: EventBus, token: str, debug: bool = False):
        super().__init__(settings, bus)
        self.token = token
        self.debug = debug
        self.exit_code = EXIT_LOGOUT
        self.base_url = ""
        self.audio = system.Audio()
        self.network = system.Network()
        self.backlight = system.Backlight()
        self.gdk_screen = Gdk.Screen.get_default()
        self.composited = self.gdk_screen.is_composited()
        self._infos: dict[str, Gio.DesktopAppInfo] = {}
        self._apps: list[dict] = []
        self._app_icons: dict[str, str | None] = {}
        self._icon_cache: dict[str, tuple[bytes, str]] = {}
        self._wm_index: dict[str, str] = {}
        self._system: dict = {}
        self._system_lock = threading.Lock()
        self._poll_stop = threading.Event()
        self._win_timer = 0
        self._apps_timer = 0
        self.settings_window: Gtk.Window | None = None
        self.setup_window: Gtk.Window | None = None
        self.files_windows: set[Gtk.Window] = set()
        self.single_windows: dict[str, Gtk.Window] = {}
        self._chooser = None
        self.procmon = ProcessMonitor(protected_pids())
        self._procs_lock = threading.Lock()

    # ==== startup ==========================================================================
    def start(self, base_url: str) -> None:
        self.base_url = base_url
        ctx = WebKit2.WebContext.get_default()
        ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        self._ucm = WebKit2.UserContentManager()
        self._ucm.add_script(WebKit2.UserScript.new(
            f"window.POLYOS = {json.dumps({'token': self.token})};",
            WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START, None, None))

        self._load_apps()
        self._app_monitor = Gio.AppInfoMonitor.get()
        self._app_monitor.connect("changed", lambda *_: self._schedule_apps_reload())
        self._init_wnck()

        self.desktop = self._surface("desktop", Gdk.WindowTypeHint.DESKTOP)
        self.desktop.set_keep_below(True)
        self.panel = self._surface("panel", Gdk.WindowTypeHint.DOCK)
        self.panel.set_keep_above(True)
        self.popup = self._surface("popup", Gdk.WindowTypeHint.UTILITY)
        self.popup.set_keep_above(True)
        self.popup.connect("focus-out-event", self._on_popup_focus_out)

        self._layout()
        self.gdk_screen.connect("monitors-changed", lambda *_: self._layout())
        self.gdk_screen.connect("size-changed", lambda *_: self._layout())
        for win in (self.desktop, self.panel):
            win.show_all()
            win.stick()
        self._refresh_system(("volume", "network", "battery", "brightness"))
        threading.Thread(target=self._poll_loop, name="polyos-poll", daemon=True).start()
        log.info("shell started (composited=%s)", self.composited)

    def quit(self, code: int = EXIT_LOGOUT):
        self.exit_code = code
        self._poll_stop.set()
        Gtk.main_quit()
        return False

    # ==== surfaces =========================================================================
    def _view(self, query: str, transparent: bool) -> WebKit2.WebView:
        view = WebKit2.WebView.new_with_user_content_manager(self._ucm)
        prefs = view.get_settings()
        prefs.set_enable_developer_extras(self.debug)
        prefs.set_enable_write_console_messages_to_stdout(True)
        color = Gdk.RGBA()
        if transparent:
            color.parse("rgba(0,0,0,0)")
        else:
            color.parse(SOLID_BG)
        view.set_background_color(color)
        view.connect("context-menu", lambda *_: not self.debug)
        view.connect("decide-policy", self._on_decide_policy)
        view.connect("web-process-terminated", self._on_web_crash)
        view.load_uri(f"{self.base_url}/index.html?{query}")
        return view

    def _surface(self, name: str, hint: Gdk.WindowTypeHint) -> Gtk.Window:
        win = Gtk.Window(title=f"PolyOS {name}")
        win.set_wmclass(f"polyos-{name}", "PolyOS")
        win.set_type_hint(hint)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        visual = self.gdk_screen.get_rgba_visual()
        transparent = self.composited and visual is not None and name != "desktop"
        if transparent:
            win.set_visual(visual)
            win.set_app_paintable(True)
        win.connect("delete-event", lambda *_: True)  # shell surfaces never close
        win.view = self._view(f"surface={name}", transparent)
        win.add(win.view)
        return win

    def _geometry(self) -> Gdk.Rectangle:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_geometry()

    def _layout(self) -> None:
        g = self._geometry()
        self.desktop.set_size_request(g.width, g.height)
        self.desktop.resize(g.width, g.height)
        self.desktop.move(g.x, g.y)
        width = g.width - 2 * DOCK_MARGIN
        self.panel.set_size_request(width, DOCK_HEIGHT)
        self.panel.resize(width, DOCK_HEIGHT)
        self.panel.move(g.x + DOCK_MARGIN, g.y + g.height - DOCK_MARGIN - DOCK_HEIGHT)

    def _x_time(self) -> int:
        try:
            return GdkX11.x11_get_server_time(self.panel.get_window())
        except Exception:
            return Gdk.CURRENT_TIME

    def _on_decide_policy(self, view, decision, dtype):
        if dtype not in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                         WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        if uri.startswith(self.base_url + "/") and dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        decision.ignore()
        if uri.startswith(("http://", "https://", "mailto:")) and not uri.startswith(self.base_url):
            try:
                Gio.AppInfo.launch_default_for_uri(uri, None)
            except GLib.Error as exc:
                log.warning("could not open %s: %s", uri, exc.message)
        return True

    def _on_web_crash(self, view, reason):
        log.error("web process for %s terminated (%s); reloading", view.get_uri(), reason)
        GLib.timeout_add(500, lambda: (view.reload(), False)[1])

    # ==== popup ============================================================================
    def _show_popup(self, popup: dict) -> None:
        GLib.idle_add(self._show_popup_main, popup)

    def _show_popup_main(self, popup: dict):
        g = self._geometry()
        if popup.get("fullscreen"):  # app launcher: whole monitor, dock stays on top
            x, y, width, height = 0, 0, g.width, g.height
        else:
            width, height = popup["width"], popup["height"]
            anchor = popup.get("anchorX")
            x = 12 if anchor is None else int(DOCK_MARGIN + anchor - width / 2)  # anchor is dock-relative
            x = max(12, min(x, g.width - width - 12))
            y = g.height - PANEL_HEIGHT - height - 4
        self.popup.set_size_request(width, height)
        self.popup.resize(width, height)
        self.popup.move(g.x + x, g.y + y)
        self.popup.show_all()
        self.popup.move(g.x + x, g.y + y)
        ts = self._x_time()
        self.popup.present_with_time(ts)
        gdk_win = self.popup.get_window()
        if gdk_win is not None:
            gdk_win.focus(ts)
        self.popup.view.grab_focus()
        if popup.get("fullscreen") and self.panel.get_window() is not None:
            self.panel.get_window().raise_()  # both are in the "above" layer
        return False

    def _hide_popup(self) -> None:
        GLib.idle_add(lambda: (self.popup.hide(), False)[1])

    def _on_popup_focus_out(self, *_):
        GLib.timeout_add(120, self._check_popup_focus)
        return False

    def _check_popup_focus(self):
        if self.popup.get_visible() and not self.popup.is_active():
            self.popup_closed()
        return False

    # ==== apps =============================================================================
    def _load_apps(self) -> None:
        theme = Gtk.IconTheme.get_default()
        infos, apps, icons = {}, [], {}
        for info in Gio.AppInfo.get_all():
            if not isinstance(info, Gio.DesktopAppInfo) or not info.should_show():
                continue
            app_id = info.get_id()
            if not app_id or app_id in infos:
                continue
            infos[app_id] = info
            apps.append({
                "id": app_id,
                "name": DISPLAY_NAMES.get(app_id) or info.get_display_name() or app_id,
                "hidden": app_id in HIDDEN_APPS,
                "description": info.get_description() or "",
                "categories": [c for c in (info.get_categories() or "").split(";") if c],
                "keywords": list(info.get_keywords() or []),
                "icon": f"/icon/app/{quote(app_id)}",
            })
            icons[app_id] = self._resolve_icon(theme, info.get_icon())
        apps.sort(key=lambda a: a["name"].casefold())

        index: dict[str, str] = {}
        for pass_no in range(3):  # StartupWMClass beats desktop id beats executable name
            for app_id, info in infos.items():
                stem = app_id[:-len(".desktop")]
                if pass_no == 0:
                    keys = [info.get_startup_wm_class()]
                elif pass_no == 1:
                    keys = [stem, stem.rsplit(".", 1)[-1]]
                else:
                    exe = Path(info.get_executable() or "").name
                    keys = [exe] if exe not in GENERIC_EXECUTABLES else []
                for key in keys:
                    if key:
                        index.setdefault(key.lower(), app_id)
        self._infos, self._apps, self._app_icons, self._wm_index = infos, apps, icons, index
        self._icon_cache.clear()

    def _schedule_apps_reload(self) -> None:
        if self._apps_timer:
            return

        def reload():
            self._apps_timer = 0
            self._load_apps()
            self.bus.publish("apps", apps=self._apps)
            self._windows_changed()
            return False

        self._apps_timer = GLib.timeout_add(500, reload)

    @staticmethod
    def _resolve_icon(theme: Gtk.IconTheme, gicon) -> str | None:
        if gicon is None:
            return None
        if isinstance(gicon, Gio.FileIcon):
            path = gicon.get_file().get_path()
            return path if path and os.path.isfile(path) else None
        if isinstance(gicon, Gio.ThemedIcon):
            names = gicon.get_names()
            for name in names:
                if os.path.isabs(name) and os.path.isfile(name):
                    return name
            info = theme.choose_icon(names, 128, 0)
            if info is not None:
                return info.get_filename()
        return None

    def apps(self) -> list[dict]:
        return self._apps

    def app_icon(self, app_id: str) -> tuple[bytes, str]:
        cached = self._icon_cache.get(app_id)
        if cached:
            return cached
        path = self._app_icons.get(app_id)
        result = None
        if path:
            ext = Path(path).suffix.lower()
            try:
                if ext in (".svg", ".png"):
                    result = (Path(path).read_bytes(), IMAGE_TYPES[ext])
                else:  # xpm, svgz, ...: convert to PNG
                    result = (on_main(self._png_from_file, path), "image/png")
            except (OSError, GLib.Error) as exc:
                log.debug("icon %s unreadable: %s", path, exc)
        if result is None:
            app = next((a for a in self._apps if a["id"] == app_id), None)
            result = (letter_icon(app["name"] if app else app_id), "image/svg+xml")
        self._icon_cache[app_id] = result
        return result

    @staticmethod
    def _png_from_file(path: str) -> bytes:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, 128, 128)
        ok, data = pixbuf.save_to_bufferv("png", [], [])
        return bytes(data)

    def launch(self, app_id: str):
        if app_id in OWN_APPS:
            self.note_launch(app_id)
            return self.open_app(OWN_APPS[app_id])
        on_main(self._launch_main, app_id)
        self.note_launch(app_id)

    def _launch_main(self, app_id: str):
        info = self._infos.get(app_id) or Gio.DesktopAppInfo.new(app_id)
        if info is None:
            raise ApiError("That app is no longer installed", 404)
        ctx = Gdk.Display.get_default().get_app_launch_context()
        ctx.set_timestamp(self._x_time())
        try:
            info.launch([], ctx)
        except GLib.Error as exc:
            raise ApiError(f"Could not start {info.get_display_name()}: {exc.message}", 500) from None

    def run_default(self, what: str):
        if what == "files":
            return self.open_app("files")
        system.run_default(what)

    def open_path(self, path: str):
        p = self.files.resolve(path)
        if p.is_dir():
            return self.open_app("files", str(p))
        if not p.exists():
            raise ApiError("That file no longer exists.", 404)
        return on_main(self._open_uri_main, p.as_uri())

    def _open_uri_main(self, uri: str):
        ctx = Gdk.Display.get_default().get_app_launch_context()
        ctx.set_timestamp(self._x_time())
        try:
            Gio.AppInfo.launch_default_for_uri(uri, ctx)
        except GLib.Error as exc:
            raise ApiError(f"No app is set up to open this file ({exc.message}).", 415) from None

    def terminal_at(self, path: str):
        folder = self.files.resolve(path)
        system.spawn(["x-terminal-emulator"] if system.have("x-terminal-emulator") else ["xterm"], cwd=str(folder))

    def run_command(self, command: str):
        system.run_command(command)
        self.popup_closed()

    def env(self) -> dict:
        installer = next((i for i in ("install-debian.desktop", "calamares.desktop") if i in self._infos), None)
        return {"dev": False, "composited": self.composited, "live": Path("/run/live/medium").exists(),
                "installer": installer, "panelHeight": PANEL_HEIGHT, "dockHeight": DOCK_HEIGHT,
                "dockMargin": DOCK_MARGIN, "version": __version__}

    # ==== windows ==========================================================================
    def _init_wnck(self) -> None:
        Wnck.set_client_type(Wnck.ClientType.PAGER)  # our requests count as direct user actions
        self.wscreen = Wnck.Screen.get_default()
        self.wscreen.force_update()
        self.wscreen.connect("window-opened", self._on_window_opened)
        self.wscreen.connect("window-closed", lambda *_: self._windows_changed())
        self.wscreen.connect("active-window-changed", self._on_active_changed)
        for win in self.wscreen.get_windows():
            self._watch_window(win)

    def _watch_window(self, win) -> None:
        for sig in ("name-changed", "state-changed", "icon-changed", "class-changed"):
            try:
                win.connect(sig, lambda *_: self._windows_changed())
            except TypeError:
                pass  # signal missing in this libwnck version

    def _on_window_opened(self, _screen, win) -> None:
        self._watch_window(win)
        self._windows_changed()

    def _on_active_changed(self, screen, _previous) -> None:
        self._windows_changed()
        active = screen.get_active_window()
        if active is not None and self._popup is not None and active.get_class_group_name() != "PolyOS":
            self.popup_closed()

    def _windows_changed(self) -> None:
        if self._win_timer:
            return

        def fire():
            self._win_timer = 0
            self.bus.publish("windows", windows=self._windows_main())
            return False

        self._win_timer = GLib.timeout_add(60, fire)

    def _match_app(self, win) -> str | None:
        for getter in ("get_class_group_name", "get_class_instance_name"):
            fn = getattr(win, getter, None)
            value = fn() if fn else None
            if value and value.lower() in self._wm_index:
                return self._wm_index[value.lower()]
        return None

    def _windows_main(self) -> list[dict]:
        active = self.wscreen.get_active_window()
        active_xid = active.get_xid() if active is not None else None
        out = []
        for win in self.wscreen.get_windows():
            if win.is_skip_tasklist() or win.get_transient() is not None:
                continue
            if win.get_window_type() not in (Wnck.WindowType.NORMAL, Wnck.WindowType.DIALOG):
                continue
            xid = win.get_xid()
            app_id = self._match_app(win)
            out.append({
                "xid": xid,
                "title": win.get_name() or "",
                "appId": app_id,
                "active": xid == active_xid,
                "minimized": win.is_minimized(),
                "icon": f"/icon/app/{quote(app_id)}" if app_id else f"/icon/window/{xid}",
            })
        return out

    def windows(self) -> list[dict]:
        return on_main(self._windows_main)

    def window_action(self, xid: int, action: str):
        return on_main(self._window_action_main, xid, action)

    def _window_action_main(self, xid: int, action: str):
        win = Wnck.Window.get(xid)
        if win is None:
            raise ApiError("That window is gone", 404)
        ts = self._x_time()
        if action == "toggle":
            action = "minimize" if win.is_active() and not win.is_minimized() else "activate"
        if action == "activate":
            if win.is_minimized():
                win.unminimize(ts)
            win.activate(ts)
        elif action == "minimize":
            win.minimize()
        elif action == "close":
            win.close(ts)
        elif action == "kill":  # "Force close": for apps that stopped responding
            pid = win.get_pid()
            if not pid:
                win.close(ts)
                return
            try:
                self.procmon.end(pid, force=True)
            except (ProcessLookupError, PermissionError) as exc:
                raise ApiError(str(exc), 409) from None

    def window_icon(self, xid: int) -> tuple[bytes, str]:
        def grab():
            win = Wnck.Window.get(xid)
            pixbuf = win.get_icon() if win is not None else None
            if pixbuf is None:
                return None
            ok, data = pixbuf.save_to_bufferv("png", [], [])
            return bytes(data) if ok else None

        data = on_main(grab)
        return (data, "image/png") if data else (letter_icon("?"), "image/svg+xml")

    # ==== system ===========================================================================
    def _refresh_system(self, parts) -> dict:
        new = {}
        if "volume" in parts:
            vol = self.audio.get()
            new["volume"] = {k: vol[k] for k in ("available", "level", "muted")}
        if "network" in parts:
            new["network"] = self.network.status()
        if "battery" in parts:
            new["battery"] = system.battery()
        if "brightness" in parts:
            new["brightness"] = self.backlight.get()
        with self._system_lock:
            changed = any(self._system.get(k) != v for k, v in new.items())
            self._system.update(new)
            snapshot = json.loads(json.dumps(self._system))
        if changed:
            self.bus.publish("system", system=snapshot)
        return snapshot

    def _poll_loop(self) -> None:
        tick = 0
        while not self._poll_stop.wait(2.0):
            tick += 1
            parts = ["volume"]
            if tick % 3 == 0:
                parts += ["network", "brightness"]
            if tick % 15 == 0:
                parts.append("battery")
            try:
                self._refresh_system(parts)
            except Exception:
                log.exception("system poll failed")

    def system_status(self) -> dict:
        with self._system_lock:
            if self._system:
                return json.loads(json.dumps(self._system))
        return self._refresh_system(("volume", "network", "battery", "brightness"))

    def set_volume(self, level=None, delta=None, muted=None, toggle_mute=False):
        self.audio.set(level=level, delta=delta, muted=muted, toggle_mute=toggle_mute)
        return self._refresh_system(("volume",))["volume"]

    def set_brightness(self, level=None, delta=None):
        self.backlight.set(level=level, delta=delta)
        return self._refresh_system(("brightness",))["brightness"]

    def wifi_list(self) -> dict:
        status = self._refresh_system(("network",))["network"]
        if not status["available"] or not status["wifiDevice"] or not status["wifiEnabled"]:
            return {"enabled": status["wifiEnabled"], "networks": []}
        return {"enabled": True, "networks": self.network.wifi_list()}

    def wifi_connect(self, ssid: str, password: str | None):
        try:
            self.network.connect(ssid, password)
        finally:
            self._refresh_system(("network",))

    def wifi_forget(self, ssid: str):
        self.network.forget(ssid)
        self._refresh_system(("network",))

    def wifi_enable(self, enabled: bool):
        self.network.set_wifi(enabled)
        time.sleep(0.5)
        self._refresh_system(("network",))

    def power(self, action: str):
        self.popup_closed()
        if action == "logout":
            GLib.idle_add(self.quit, EXIT_LOGOUT)
            return
        system.power(action)

    def sysinfo(self) -> dict:
        return system.sysinfo()

    def restart_shell(self):
        GLib.idle_add(self.quit, EXIT_RESTART)

    # ==== app windows (Settings, Files, first-run setup) ======================================
    def open_app(self, name: str, page: str | None = None):
        if name in SINGLE_WINDOWS:
            GLib.idle_add(self._open_single_main, name, page)
            return
        handler = {"settings": self._open_settings_main, "files": self._open_files_main,
                   "setup": self._open_setup_main}[name]
        GLib.idle_add(handler, page)

    def _open_single_main(self, name: str, page: str | None):
        win = self.single_windows.get(name)
        if win is not None:
            if page:
                self.bus.publish("navigate", surface=SINGLE_WINDOWS[name][0], page=page)
            win.present_with_time(self._x_time())
            return False
        surface, title, wmclass, size = SINGLE_WINDOWS[name]
        query = f"surface={surface}" + (f"&page={quote(page)}" if page else "")
        win = self._app_window(query, title, wmclass, size)
        win.connect("destroy", lambda *_: self.single_windows.pop(name, None))
        self.single_windows[name] = win
        win.show_all()
        return False

    def _app_window(self, query: str, title: str, wmclass: str, size: tuple[int, int]) -> Gtk.Window:
        win = Gtk.Window(title=title)
        win.set_wmclass(wmclass, wmclass)
        win.set_icon_name(wmclass)
        win.set_default_size(*size)
        win.set_position(Gtk.WindowPosition.CENTER)
        win.view = self._view(query, transparent=False)
        # the page's <title> becomes the window title (e.g. the folder a Files window shows)
        win.view.connect("notify::title", lambda view, _p: win.set_title(view.get_title() or title))
        win.add(win.view)
        return win

    def _open_settings_main(self, page: str | None):
        if self.settings_window is None:
            query = "surface=settings" + (f"&page={quote(page)}" if page else "")
            win = self._app_window(query, "Settings", "polyos-settings", (1000, 680))
            win.connect("destroy", lambda *_: setattr(self, "settings_window", None))
            self.settings_window = win
            win.show_all()
        else:
            if page:
                self.bus.publish("navigate", surface="settings", page=page)
            self.settings_window.present_with_time(self._x_time())
        return False

    def _open_files_main(self, path: str | None):
        query = "surface=files" + (f"&path={quote(path)}" if path else "")
        win = self._app_window(query, "Files", "polyos-files", (1080, 700))
        win.connect("destroy", lambda w: self.files_windows.discard(w))
        self.files_windows.add(win)
        win.show_all()
        return False

    def _open_setup_main(self, _page=None):
        if self.setup_window is not None:
            self.setup_window.present_with_time(self._x_time())
            return False
        win = self._app_window("surface=setup", "Welcome to PolyOS", "polyos-setup", (1100, 720))
        win.set_decorated(False)
        win.fullscreen()
        win.connect("destroy", lambda *_: setattr(self, "setup_window", None))
        self.setup_window = win
        win.show_all()
        return False

    # ==== Task Manager =====================================================================
    def _windows_with_pids(self) -> list[dict]:
        out = []
        by_id = {a["id"]: a for a in self._apps}
        for win in self._windows_main():
            wnck_win = Wnck.Window.get(win["xid"])
            app = by_id.get(win["appId"]) if win["appId"] else None
            out.append({**win, "pid": wnck_win.get_pid() if wnck_win is not None else 0,
                        "name": app["name"] if app else win["title"]})
        return out

    def procs(self) -> dict:
        windows = on_main(self._windows_with_pids)
        with self._procs_lock:
            return self.procmon.sample(windows)

    def procs_end(self, pid: int, force: bool):
        try:
            self.procmon.end(pid, force)
        except ProcessLookupError as exc:
            raise ApiError(str(exc), 404) from None
        except PermissionError as exc:
            raise ApiError(str(exc) if "PolyOS" in str(exc) else "You can't end that process.", 403) from None

    def theme_icon(self, name: str) -> tuple[bytes, str]:
        if not name or len(name) > 120 or "/" in name or name.startswith("."):
            return letter_icon("?"), "image/svg+xml"
        cached = self._icon_cache.get("theme:" + name)
        if cached:
            return cached

        names = [n for n in name.split(",") if n][:6]  # candidates, best first

        def find():
            info = Gtk.IconTheme.get_default().choose_icon(names, 128, 0)
            return info.get_filename() if info is not None else None

        path = on_main(find)
        result = None
        if path:
            ext = Path(path).suffix.lower()
            try:
                result = (Path(path).read_bytes(), IMAGE_TYPES[ext]) if ext in (".svg", ".png") else \
                    (on_main(self._png_from_file, path), "image/png")
            except (OSError, GLib.Error):
                result = None
        result = result or (letter_icon(names[0].split(".")[-1] if names else "?"), "image/svg+xml")
        self._icon_cache["theme:" + name] = result
        return result

    def update_settings(self, patch: dict) -> dict:
        settings = super().update_settings(patch)
        if "theme" in patch:
            try:
                theme.apply_gtk(settings["theme"])
            except OSError as exc:
                log.warning("could not write GTK settings: %s", exc)
            theme.switch_openbox(paths.runtime_dir() / "openbox-rc.xml", settings["theme"])
        if "showAllApps" in patch:
            self.bus.publish("apps", apps=self._apps)
        return settings

    def finish_setup(self):
        self.update_settings({"setupDone": True})
        GLib.idle_add(lambda: (self.setup_window.destroy() if self.setup_window else None, False)[1])

    def pick_wallpaper(self):
        GLib.idle_add(self._pick_wallpaper_main)
        return {"ok": True, "pending": True}

    def _pick_wallpaper_main(self):
        dialog = Gtk.FileChooserNative.new("Choose a wallpaper", self.settings_window,
                                           Gtk.FileChooserAction.OPEN, "_Set Wallpaper", "_Cancel")
        images = Gtk.FileFilter()
        images.set_name("Images")
        for ext in IMAGE_TYPES:
            images.add_pattern(f"*{ext}")
            images.add_pattern(f"*{ext.upper()}")
        dialog.add_filter(images)
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        if pictures and os.path.isdir(pictures):
            dialog.set_current_folder(pictures)

        def on_response(chooser, response):
            if response == Gtk.ResponseType.ACCEPT and chooser.get_filename():
                try:
                    self.update_settings({"wallpaper": chooser.get_filename()})
                except ApiError as exc:
                    log.warning("wallpaper rejected: %s", exc)
            self._chooser = None

        dialog.connect("response", on_response)
        self._chooser = dialog  # keep a reference while the dialog is open
        dialog.show()
        return False

    # ==== XDG autostart ====================================================================
    def run_autostart(self):
        dirs = [Path(GLib.get_user_config_dir()) / "autostart"]
        dirs += [Path(d) / "autostart" for d in GLib.get_system_config_dirs()]
        seen: set[str] = set()
        for directory in dirs:
            if not directory.is_dir():
                continue
            for entry in sorted(directory.glob("*.desktop")):
                if entry.name in seen:
                    continue
                seen.add(entry.name)  # a user file overrides the system one, even if hidden
                info = Gio.DesktopAppInfo.new_from_filename(str(entry))
                if info is None or info.get_is_hidden() or not info.get_show_in(None):
                    continue
                if (info.get_string("X-GNOME-Autostart-enabled") or "").lower() == "false":
                    continue
                try:
                    info.launch([], None)
                    log.info("autostart: %s", entry.name)
                except GLib.Error as exc:
                    log.warning("autostart %s failed: %s", entry.name, exc.message)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="polyos-shell", description="PolyOS desktop shell")
    parser.add_argument("--debug", action="store_true", help="verbose logs and the web inspector")
    parser.add_argument("--autostart", action="store_true", help="run XDG autostart entries")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    initialized, _ = Gtk.init_check(sys.argv)
    if not initialized:
        log.error("cannot open the X display (DISPLAY=%s)", os.environ.get("DISPLAY"))
        return 1

    settings = Settings(paths.config_dir() / "settings.json")
    bus = EventBus()
    token = secrets.token_urlsafe(32)
    shell = DesktopShell(settings, bus, token, debug=args.debug)
    server = Server(shell, paths.UI_DIR, token)
    server.start()
    paths.write_runtime_info({"port": server.port, "token": token, "pid": os.getpid(), "version": __version__})

    shell.start(server.base_url)
    if not settings.get("setupDone"):
        shell.open_app("setup")  # live USB: the installer; first sign-in: PolyOS's welcome
    if args.autostart:
        GLib.timeout_add_seconds(2, shell.run_autostart)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, shell.quit, EXIT_LOGOUT)
    try:
        Gtk.main()
    finally:
        server.stop()
        paths.clear_runtime_info(os.getpid())
    return shell.exit_code


if __name__ == "__main__":
    sys.exit(main())
