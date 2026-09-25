"""Dark / light appearance for everything outside the web UI: GTK apps and Openbox."""

from __future__ import annotations

import configparser
import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger("polyos.theme")

OPENBOX_THEMES = {"dark": "PolyOS", "light": "PolyOS-Light"}
GTK_KEYS = {
    "dark": {"gtk-application-prefer-dark-theme": "1", "gtk-icon-theme-name": "Papirus-Dark"},
    "light": {"gtk-application-prefer-dark-theme": "0", "gtk-icon-theme-name": "Papirus"},
}


def _config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    return Path(value) if value else Path.home() / ".config"


def apply_gtk(theme: str, config_home: Path | None = None) -> None:
    """Set the appearance keys in the user's GTK 3/4 settings.ini, keeping their other settings."""
    keys = GTK_KEYS.get(theme, GTK_KEYS["dark"])
    for version in ("gtk-3.0", "gtk-4.0"):
        path = (config_home or _config_home()) / version / "settings.ini"
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        try:
            cfg.read(path, encoding="utf-8")
        except (configparser.Error, OSError) as exc:
            log.warning("rewriting unreadable %s: %s", path, exc)
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.optionxform = str
        if not cfg.has_section("Settings"):
            cfg.add_section("Settings")
        changed = False
        for key, value in keys.items():
            if cfg["Settings"].get(key) != value:
                cfg["Settings"][key] = value
                changed = True
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                cfg.write(fh, space_around_delimiters=False)


def openbox_rc(template: str, theme: str, panel_margin: int) -> str:
    return (template.replace("@PANEL_MARGIN@", str(panel_margin))
            .replace("@THEME@", OPENBOX_THEMES.get(theme, OPENBOX_THEMES["dark"])))


def switch_openbox(rc_path: Path, theme: str) -> bool:
    """Point the running Openbox at the matching theme and reload it."""
    try:
        text = rc_path.read_text("utf-8")
    except OSError:
        return False
    name = OPENBOX_THEMES.get(theme, OPENBOX_THEMES["dark"])
    new = re.sub(r"(<theme>\s*<name>)[^<]*(</name>)", rf"\g<1>{name}\g<2>", text, count=1)
    if new == text:
        return True
    rc_path.write_text(new, "utf-8")
    try:
        subprocess.run(["openbox", "--reconfigure"], check=False, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return True
