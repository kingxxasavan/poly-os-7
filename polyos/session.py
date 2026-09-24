"""The PolyOS X session (started by LightDM through /usr/share/xsessions/polyos.desktop).

Sets up the environment and display scale, starts openbox, the compositor and helpers,
then supervises the shell: exit code 0 logs out, 3 restarts it, anything else is a crash.
"""

from __future__ import annotations

import collections
import logging
import os
import shutil
import signal
import subprocess
import sys
import time

from . import paths, system
from .backend import PANEL_HEIGHT
from .core import Settings

log = logging.getLogger("polyos.session")

EXIT_LOGOUT, EXIT_RESTART = 0, 3
POLKIT_AGENTS = [
    "/usr/bin/lxpolkit",
    "/usr/libexec/polkit-mate-authentication-agent-1",
    "/usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1",
    "/usr/libexec/polkit-gnome-authentication-agent-1",
]
ACTIVATION_VARS = ["DISPLAY", "XAUTHORITY", "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION",
                   "XDG_CONFIG_DIRS", "GDK_SCALE", "GDK_DPI_SCALE", "QT_ENABLE_HIGHDPI_SCALING", "XCURSOR_SIZE"]
LOG_LIMIT = 1024 * 1024


def _rotate(path) -> None:
    try:
        if path.stat().st_size > LOG_LIMIT:
            path.replace(path.with_name(path.name + ".1"))
    except FileNotFoundError:
        pass


class Session:
    def __init__(self):
        self.children: list[subprocess.Popen] = []
        self.shell: subprocess.Popen | None = None
        self.stopping = False
        self.state = paths.state_dir()
        self.helper_log = open(self.state / "helpers.log", "ab")  # noqa: SIM115 - lives as long as the session

    def spawn(self, args: list[str]) -> subprocess.Popen | None:
        if not (os.path.isabs(args[0]) and os.path.exists(args[0])) and not shutil.which(args[0]):
            log.info("skipping %s (not installed)", args[0])
            return None
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.helper_log, stderr=subprocess.STDOUT)
        self.children.append(proc)
        return proc

    # ---- setup ---------------------------------------------------------------------------
    def setup_env(self) -> None:
        os.environ.update(XDG_CURRENT_DESKTOP="PolyOS", XDG_SESSION_DESKTOP="polyos", DESKTOP_SESSION="polyos")
        dirs = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
        if str(paths.XDG_DIR) not in dirs.split(":"):
            os.environ["XDG_CONFIG_DIRS"] = f"{paths.XDG_DIR}:{dirs}"  # our GTK defaults first
        if paths.IN_REPO:
            os.environ["PATH"] = f"{paths.BIN_DIR}:{os.environ.get('PATH', '')}"

    def setup_scale(self, settings: Settings) -> int:
        pref = settings.get("scale")
        if pref == "auto":
            rc, out = system.run(["xrandr", "--query"], 5)
            scale = system.auto_scale(system.parse_xrandr_dpi(out) if rc == 0 else None)
        else:
            scale = int(pref)
        if scale > 1 and "GDK_SCALE" not in os.environ:
            os.environ.update(GDK_SCALE=str(scale), GDK_DPI_SCALE=str(1 / scale),
                              QT_ENABLE_HIGHDPI_SCALING="1", XCURSOR_SIZE=str(24 * scale))
            if system.have("xrdb"):
                subprocess.run(["xrdb", "-merge"], input=f"Xft.dpi: {96 * scale}\nXcursor.size: {24 * scale}\n",
                               text=True, check=False)
        log.info("display scale %s (setting: %s)", scale, pref)
        return scale

    def update_activation_env(self) -> None:
        if system.have("dbus-update-activation-environment"):
            names = [v for v in ACTIVATION_VARS if v in os.environ]
            subprocess.run(["dbus-update-activation-environment", "--systemd", *names], check=False,
                           stdout=self.helper_log, stderr=subprocess.STDOUT)

    def start_window_manager(self, scale: int) -> None:
        user_rc = paths.config_dir() / "openbox" / "rc.xml"
        source = user_rc if user_rc.is_file() else paths.OPENBOX_RC
        rc_path = paths.runtime_dir() / "openbox-rc.xml"
        rc_path.write_text(source.read_text("utf-8").replace("@PANEL_MARGIN@", str(PANEL_HEIGHT * scale)), "utf-8")
        if self.spawn(["openbox", "--config-file", str(rc_path)]) is None:
            log.error("openbox is missing; windows will have no decorations")
            return
        for _ in range(50):  # wait until the WM owns the screen so our windows get managed
            rc, out = system.run(["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"], 1)
            if rc == 0 and "window id" in out:
                return
            time.sleep(0.1)
        log.warning("openbox did not announce itself within 5 s")

    def start_compositor(self) -> None:
        user_conf = paths.config_dir() / "picom.conf"
        conf = str(user_conf if user_conf.is_file() else paths.PICOM_CONF)
        proc = self.spawn(["picom", "--config", conf])
        if proc is None:
            return
        time.sleep(1.5)
        if proc.poll() is not None:  # no working OpenGL (common in VMs): software fallback
            log.warning("picom (glx) exited with %s; retrying with xrender", proc.returncode)
            proc = self.spawn(["picom", "--config", conf, "--backend", "xrender"])
            time.sleep(1.0)
            if proc is not None and proc.poll() is not None:
                log.warning("picom unavailable; running without effects")

    def start_helpers(self) -> None:
        self.spawn(["xcape", "-e", "Super_L=Alt_L|F1;Super_R=Alt_L|F1"])  # tap Super = Start menu
        agent = next((a for a in POLKIT_AGENTS if os.path.exists(a)), None)
        if agent:
            self.spawn([agent])

    # ---- shell supervision -----------------------------------------------------------------
    def supervise_shell(self) -> None:
        shell_log = self.state / "shell.log"
        crashes: collections.deque[float] = collections.deque()
        first = True
        while not self.stopping:
            _rotate(shell_log)
            args = paths.command("polyos-shell") + (["--autostart"] if first else [])
            with open(shell_log, "ab") as out:
                self.shell = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
                rc = self.shell.wait()
            first = False
            if self.stopping or rc == EXIT_LOGOUT:
                return
            if rc == EXIT_RESTART:
                continue
            log.error("shell exited with status %s", rc)
            now = time.monotonic()
            crashes.append(now)
            while crashes and now - crashes[0] > 60:
                crashes.popleft()
            if len(crashes) >= 4:
                if not self.ask_retry(shell_log):
                    return
                crashes.clear()
            time.sleep(1)

    def ask_retry(self, shell_log) -> bool:
        if not system.have("xmessage"):
            return False
        message = (f"The PolyOS shell keeps crashing.\n\nDetails are in {shell_log}\n\n"
                   "Retry, open a terminal to investigate, or log out.")
        rc = subprocess.run(["xmessage", "-center", "-buttons", "Retry:2,Terminal:3,Log out:0", message],
                            check=False).returncode
        if rc == 3:
            subprocess.run(["x-terminal-emulator"], check=False)
            return True
        return rc == 2

    def run(self) -> int:
        if not os.environ.get("DISPLAY"):
            log.error("DISPLAY is not set; polyos-session must run inside an X session")
            return 1
        settings = Settings(paths.config_dir() / "settings.json")
        self.setup_env()
        scale = self.setup_scale(settings)
        self.update_activation_env()
        if system.have("xsetroot"):
            subprocess.run(["xsetroot", "-solid", "#151515", "-cursor_name", "left_ptr"], check=False)
        self.start_window_manager(scale)
        if settings.get("effects"):
            self.start_compositor()
        self.start_helpers()
        self.supervise_shell()
        return 0

    def shutdown(self) -> None:
        for proc in [self.shell, *reversed(self.children)]:
            if proc is not None and proc.poll() is None:
                proc.terminate()
        deadline = time.monotonic() + 3
        for proc in [self.shell, *self.children]:
            if proc is None:
                continue
            try:
                proc.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    session = Session()
    logging.basicConfig(filename=session.state / "session.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("---- session start (pid %s)", os.getpid())

    def on_signal(signum, _frame):
        log.info("received signal %s; ending session", signum)
        session.stopping = True
        if session.shell is not None and session.shell.poll() is None:
            session.shell.terminate()

    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, on_signal)
    try:
        return session.run()
    except Exception:
        log.exception("session failed")
        return 1
    finally:
        session.shutdown()
        log.info("---- session end")


if __name__ == "__main__":
    sys.exit(main())
