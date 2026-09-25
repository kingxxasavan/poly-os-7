"""PolyMarket: the PolyOS catalog of trusted apps (data/store/catalog.json).

The catalog is the allowlist: polyos-admin reads it again as root and installs only the
Debian packages or Flathub apps listed there, never names sent by the UI.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import paths
from .arch import ARCHES, debian_arch

SOURCES = ("debian", "flathub")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_PKG = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,80}$")
_REF = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2,}$")
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"
# where Debian packages and Flathub put app launchers (plus the per-user ones under ~/.local/share)
LAUNCHER_DIRS = ("/usr/share/applications", "/usr/local/share/applications", "/var/lib/flatpak/exports/share/applications")


class CatalogError(ValueError):
    pass


def validate(data: dict) -> dict:
    """Check the catalog's shape; returns {id: app}."""
    cats = {c[0] for c in data.get("categories", [])}
    apps = {}
    for app in data.get("apps", []):
        aid = app.get("id", "")
        if not _ID.match(aid) or aid in apps:
            raise CatalogError(f"bad or duplicate id: {aid!r}")
        if app.get("source") not in SOURCES:
            raise CatalogError(f"{aid}: unknown source")
        if app.get("category") not in cats:
            raise CatalogError(f"{aid}: unknown category")
        if app["source"] == "debian":
            pkgs = app.get("packages") or []
            if not pkgs or not all(_PKG.match(p) for p in pkgs):
                raise CatalogError(f"{aid}: bad package list")
        elif not _REF.match(app.get("ref", "")):
            raise CatalogError(f"{aid}: bad Flathub id")
        if "arches" in app and not (isinstance(app["arches"], list) and app["arches"]
                                    and all(a in ARCHES for a in app["arches"])):
            raise CatalogError(f"{aid}: bad arches")
        for key in ("name", "summary", "description"):
            if not isinstance(app.get(key), str) or not app[key]:
                raise CatalogError(f"{aid}: missing {key}")
        apps[aid] = app
    for name, pack in (data.get("packs") or {}).items():
        if not _ID.match(name) or not isinstance(pack.get("apps"), list) or not pack["apps"]:
            raise CatalogError(f"bad pack: {name!r}")
        for item in pack["apps"]:
            if not (isinstance(item, list) and len(item) == 2 and item[0] in apps and isinstance(item[1], bool)):
                raise CatalogError(f"pack {name}: bad app {item!r}")
    return apps


def available(app: dict, arch: str | None = None) -> bool:
    """Whether this app exists for this computer's processor (Steam, Chrome... are Intel/AMD only)."""
    return (arch or debian_arch()) in app.get("arches", ARCHES)


def for_arch(data: dict, arch: str | None = None) -> dict:
    """The catalog without apps this computer can't run (and packs without them)."""
    arch = arch or debian_arch()
    apps = [a for a in data["apps"] if available(a, arch)]
    ids = {a["id"] for a in apps}
    packs = {name: {**info, "apps": [item for item in info["apps"] if item[0] in ids]}
             for name, info in (data.get("packs") or {}).items()}
    return {**data, "apps": apps, "packs": packs}


def pack(data: dict, name: str) -> dict | None:
    """A pack ("gaming", "developer") with its apps, or None."""
    return (data.get("packs") or {}).get(name)


def installed_launcher(app: dict, home: Path, dirs=LAUNCHER_DIRS) -> str | None:
    """The launcher (.desktop id) an installed app put on the system, if any."""
    folders = [Path(d) for d in dirs] + [home / ".local/share/applications", home / ".local/share/flatpak/exports/share/applications"]
    for desktop_id in app.get("desktop") or []:
        if any((folder / desktop_id).is_file() for folder in folders):
            return desktop_id
    return None


DESKTOP_ID = re.compile(r"^[\w.+-]{1,120}\.desktop$")


def launcher_path(desktop_id: str, home: Path, dirs=LAUNCHER_DIRS) -> Path | None:
    """The .desktop file behind an app (yours first, as the launcher list sees it)."""
    if not DESKTOP_ID.match(desktop_id):
        return None
    for folder in [home / ".local/share/applications", home / ".local/share/flatpak/exports/share/applications", *map(Path, dirs)]:
        if (folder / desktop_id).is_file():
            return folder / desktop_id
    return None


def app_origin(desktop_id: str, home: Path, dirs=LAUNCHER_DIRS) -> dict:
    """Where an app came from: a Debian package, a Flatpak (system or yours), or a launcher in your home folder."""
    path = launcher_path(desktop_id, home, dirs)
    if path is None:
        return {"kind": "unknown"}
    mine = home in path.parents
    if "/flatpak/exports/" in str(path):
        return {"kind": "flatpak", "path": str(path), "ref": desktop_id[:-len(".desktop")], "user": mine}
    return {"kind": "local" if mine else "debian", "path": str(path)}


def parse_dpkg_search(text: str) -> dict[str, str]:
    """`dpkg -S FILE...` lines ("pkg: /path", "pkg1, pkg2: /path") -> {path: first package}."""
    owners = {}
    for line in text.splitlines():
        if line.startswith("diversion ") or ": " not in line:
            continue
        pkgs, path = line.split(": ", 1)
        owners[path.strip()] = pkgs.split(",")[0].strip().split(":")[0]  # drop the :arch suffix
    return owners


def debian_owners(paths: list[str]) -> dict[str, str]:
    return parse_dpkg_search(_run(["dpkg", "-S", *paths], timeout=30)) if paths and shutil.which("dpkg") else {}


def load(path: Path | None = None) -> dict:
    data = json.loads((path or paths.STORE_CATALOG).read_text("utf-8"))
    validate(data)
    return data


def _run(args: list[str], timeout: float = 20) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def installed_debian(packages: list[str]) -> set[str]:
    if not packages or not shutil.which("dpkg-query"):
        return set()
    out = _run(["dpkg-query", "-W", "-f", "${Package} ${db:Status-Abbrev}\n", *packages])
    return {ln.split()[0] for ln in out.splitlines() if len(ln.split()) > 1 and ln.split()[1].startswith("ii")}


def installed_flatpaks() -> set[str]:
    if not shutil.which("flatpak"):
        return set()
    return {ln.strip() for ln in _run(["flatpak", "list", "--app", "--columns=application"]).splitlines() if ln.strip()}


def catalog_with_status(data: dict) -> dict:
    data = for_arch(data)
    debs = installed_debian(sorted({p for a in data["apps"] if a["source"] == "debian" for p in a["packages"]}))
    flats = installed_flatpaks()
    apps = []
    for app in data["apps"]:
        if app["source"] == "debian":
            installed = all(p in debs for p in app["packages"])
        else:
            installed = app["ref"] in flats
        apps.append({**app, "installed": installed})
    return {"categories": data["categories"], "apps": apps, "flatpak": bool(shutil.which("flatpak"))}


def packs_with_status(data: dict) -> dict:
    """The editions' app packs for Settings and the welcome screens, with what's installed."""
    by_id = {a["id"]: a for a in catalog_with_status(data)["apps"]}
    out = {}
    for name, info in (for_arch(data).get("packs") or {}).items():
        out[name] = {"name": info["name"], "summary": info["summary"],
                     "apps": [{**by_id[aid], "default": default} for aid, default in info["apps"]]}
    return out
