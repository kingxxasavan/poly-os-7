"""PolyOS Gaming: cloud gaming shortcuts and opening them in the best browser for streaming.

Cloud services stream games to a browser tab, so they need no install or graphics driver.
PolyOS ships a launcher for each one (/usr/share/applications/polyos-cloud-*.desktop) and
Chromium to run them in; a service's launcher stays out of your apps until you switch it on in
Settings > Gaming (the "cloudGaming" setting), so turning one on installs nothing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# id: (name, address, what it is)
CLOUD = {
    "geforcenow": ("GeForce NOW", "https://play.geforcenow.com", "Play your Steam, Epic and Ubisoft games on NVIDIA's servers"),
    "xcloud": ("Xbox Cloud Gaming", "https://www.xbox.com/play", "Game Pass Ultimate games, streamed"),
    "luna": ("Amazon Luna", "https://luna.amazon.com", "Games with Prime and Luna channels"),
    "boosteroid": ("Boosteroid", "https://cloud.boosteroid.com", "Stream games you own from many stores"),
}
PREFIX = "polyos-cloud-"


def shortcut(cloud_id: str) -> str:
    name, _url, comment = CLOUD[cloud_id]
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={name}\nComment={comment} (cloud gaming)\n"
            f"Exec=polyos-ctl cloud {cloud_id}\nIcon=polyos-cloud-gaming\nTerminal=false\n"
            "Categories=Game;\nKeywords=cloud;stream;gaming;\nStartupNotify=true\n")


def apps_dir(home: Path) -> Path:
    return home / ".local" / "share" / "applications"


def installed(home: Path) -> list[str]:
    """Services switched on the old way (a launcher in your home folder, before PolyOS shipped them)."""
    folder = apps_dir(home)
    return [cid for cid in CLOUD if (folder / f"{PREFIX}{cid}.desktop").is_file()]


def enabled(settings, home: Path) -> list[str]:
    """Services whose launcher shows in your apps."""
    on = set(settings.get("cloudGaming") or []) | set(installed(home))
    return [cid for cid in CLOUD if cid in on]


def set_enabled(settings, home: Path, wanted: list[str]) -> list[str]:
    """Switch services on or off (a setting); old per-person launchers are tidied away."""
    for cid in CLOUD:
        (apps_dir(home) / f"{PREFIX}{cid}.desktop").unlink(missing_ok=True)
    settings.update({"cloudGaming": [cid for cid in CLOUD if cid in wanted]})
    return enabled(settings, home)


def cloud_id(app_id: str) -> str | None:
    """polyos-cloud-xcloud.desktop -> xcloud"""
    if app_id.startswith(PREFIX) and app_id.endswith(".desktop"):
        return app_id[len(PREFIX):-len(".desktop")]
    return None


def browser_command(url: str, have=shutil.which, flatpaks: set[str] | None = None) -> list[str]:
    """Chrome (Flathub) or Chromium as an app window, else the default browser."""
    if flatpaks is None:
        flatpaks = set()
        if have("flatpak"):
            try:
                out = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True,
                                     text=True, timeout=10).stdout
                flatpaks = {ln.strip() for ln in out.splitlines()}
            except (OSError, subprocess.SubprocessError):
                pass
    if "com.google.Chrome" in flatpaks:
        return ["flatpak", "run", "com.google.Chrome", f"--app={url}", "--start-maximized"]
    for exe in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        if have(exe):
            return [exe, f"--app={url}", "--start-maximized"]
    return ["xdg-open", url]


def open_cloud(cloud_id: str) -> None:
    if cloud_id not in CLOUD:
        raise ValueError(f"unknown cloud gaming service: {cloud_id}")
    subprocess.Popen(browser_command(CLOUD[cloud_id][1]), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
