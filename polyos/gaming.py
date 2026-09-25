"""PolyOS Gaming: cloud gaming shortcuts and opening them in the best browser for streaming.

Cloud services stream games to a browser tab, so they need no install or graphics driver.
They work best in a Chromium-based browser (Chrome from PolyMarket, or Chromium); Firefox is
the fallback. Shortcuts are ordinary .desktop files in ~/.local/share/applications, so they
show in the launcher and can be pinned or put on the desktop.
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
    folder = apps_dir(home)
    return [cid for cid in CLOUD if (folder / f"{PREFIX}{cid}.desktop").is_file()]


def set_shortcuts(home: Path, wanted: list[str]) -> list[str]:
    """Add the chosen services' shortcuts and remove the others. Returns what's installed now."""
    folder = apps_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    for cid in CLOUD:
        path = folder / f"{PREFIX}{cid}.desktop"
        if cid in wanted:
            path.write_text(shortcut(cid), "utf-8")
        else:
            path.unlink(missing_ok=True)
    return installed(home)


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
