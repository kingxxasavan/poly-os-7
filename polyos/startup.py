"""Startup apps (Settings > Apps): the XDG autostart entries PolyOS runs when you sign in.

System entries live in /etc/xdg/autostart and yours in ~/.config/autostart, where a file with
the same name overrides the system one (the shell's run_autostart follows the same rules).
Switching an entry off writes that override with Hidden=true, the standard way; switching it
back on removes the override again. Adding an app copies its launcher into ~/.config/autostart.
"""

from __future__ import annotations

import configparser
import os
import re
from pathlib import Path

ID_RE = re.compile(r"^[\w.+-]{1,120}\.desktop$")
PROTECTED = ("polyos",)  # PolyOS's own session pieces stay on


def system_dirs() -> list[Path]:
    return [Path(d) / "autostart" for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]


def user_dir(home: Path) -> Path:
    return home / ".config" / "autostart"


def read_entry(path: Path) -> dict:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # keys are case-sensitive
    try:
        parser.read_string(path.read_text("utf-8", "replace"))
    except (OSError, configparser.Error):
        return {}
    return dict(parser["Desktop Entry"]) if parser.has_section("Desktop Entry") else {}


def _on(entry: dict) -> bool:
    return entry.get("Hidden", "").lower() != "true" and entry.get("X-GNOME-Autostart-enabled", "").lower() != "false"


def _shows_here(entry: dict, desktops: list[str]) -> bool:
    only = [d for d in entry.get("OnlyShowIn", "").split(";") if d]
    never = [d for d in entry.get("NotShowIn", "").split(";") if d]
    if only and not any(d in only for d in desktops):
        return False
    return not any(d in never for d in desktops)


def entries(home: Path, systems: list[Path] | None = None, desktops: list[str] | None = None) -> list[dict]:
    """Every startup entry that applies to this desktop, with whether it's on."""
    if desktops is None:
        desktops = [d for d in (os.environ.get("XDG_CURRENT_DESKTOP") or "PolyOS").split(":") if d]
    systems = system_dirs() if systems is None else systems
    found: dict[str, dict] = {}
    for folder in [*reversed(systems), user_dir(home)]:  # later folders override earlier ones
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.desktop")):
            entry = read_entry(path)
            base = found.get(path.name, {}).get("_entry", {})
            merged = {**base, **entry} if folder == user_dir(home) else entry
            found[path.name] = {"_entry": merged, "_system": found.get(path.name, {}).get("_system") or folder != user_dir(home)}
    out = []
    for name, item in sorted(found.items()):
        entry = item["_entry"]
        if not entry.get("Name") or entry.get("Type", "Application") != "Application" or not _shows_here(entry, desktops):
            continue
        if entry.get("Hidden", "").lower() == "true" and not item["_system"]:
            continue  # your own entry, removed
        out.append({"id": name, "name": entry["Name"], "comment": entry.get("Comment", ""), "icon": entry.get("Icon", ""),
                    "enabled": _on(entry), "own": not item["_system"],
                    "locked": name.startswith(PROTECTED)})
    return sorted(out, key=lambda e: e["name"].casefold())


def _set_keys(text: str, values: dict[str, str]) -> str:
    """Set keys in a .desktop file's [Desktop Entry] section, keeping everything else."""
    lines, section, done = text.splitlines(), None, set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "[Desktop Entry]":
                out += [f"{k}={v}" for k, v in values.items() if k not in done]
                done.update(values)
            section = stripped
        elif section == "[Desktop Entry]" and "=" in line and line.split("=", 1)[0].strip() in values:
            key = line.split("=", 1)[0].strip()
            out.append(f"{key}={values[key]}")
            done.add(key)
            continue
        out.append(line)
    if section == "[Desktop Entry]":
        out += [f"{k}={v}" for k, v in values.items() if k not in done]
    elif "[Desktop Entry]" not in text:
        out = ["[Desktop Entry]", *[f"{k}={v}" for k, v in values.items()]]
    return "\n".join(out) + "\n"


def set_enabled(home: Path, entry_id: str, on: bool, systems: list[Path] | None = None) -> None:
    if not ID_RE.match(entry_id):
        raise ValueError("That isn't a startup app.")
    if entry_id.startswith(PROTECTED):
        raise ValueError("PolyOS needs this to start.")
    systems = system_dirs() if systems is None else systems
    system_file = next((d / entry_id for d in systems if (d / entry_id).is_file()), None)
    mine = user_dir(home) / entry_id
    if on:
        if mine.is_file():
            entry = read_entry(mine)
            if system_file and set(entry) <= {"Type", "Name", "Hidden", "X-GNOME-Autostart-enabled"}:
                mine.unlink()  # only our "off" override: remove it and the system entry applies again
            else:
                mine.write_text(_set_keys(mine.read_text("utf-8"), {"Hidden": "false", "X-GNOME-Autostart-enabled": "true"}), "utf-8")
        return
    mine.parent.mkdir(parents=True, exist_ok=True)
    if mine.is_file():
        mine.write_text(_set_keys(mine.read_text("utf-8"), {"Hidden": "true"}), "utf-8")
    elif system_file:
        name = read_entry(system_file).get("Name", entry_id)
        mine.write_text(f"[Desktop Entry]\nType=Application\nName={name}\nHidden=true\n", "utf-8")
    else:
        raise ValueError("That startup app is no longer there.")


def add(home: Path, launcher: Path) -> str:
    """Start an app when you sign in: a copy of its launcher in ~/.config/autostart."""
    if not ID_RE.match(launcher.name) or not launcher.is_file():
        raise ValueError("That app can't start automatically.")
    target = user_dir(home) / launcher.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_set_keys(launcher.read_text("utf-8", "replace"), {"Hidden": "false", "X-GNOME-Autostart-enabled": "true"}), "utf-8")
    return launcher.name


def remove(home: Path, entry_id: str, systems: list[Path] | None = None) -> None:
    """Take one of your own startup apps off the list (system ones are switched off instead)."""
    if not ID_RE.match(entry_id):
        raise ValueError("That isn't a startup app.")
    systems = system_dirs() if systems is None else systems
    if any((d / entry_id).is_file() for d in systems):
        set_enabled(home, entry_id, False, systems)
    else:
        (user_dir(home) / entry_id).unlink(missing_ok=True)
