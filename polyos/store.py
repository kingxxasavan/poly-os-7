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

SOURCES = ("debian", "flathub")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_PKG = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,80}$")
_REF = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2,}$")
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"


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
        for key in ("name", "summary", "description"):
            if not isinstance(app.get(key), str) or not app[key]:
                raise CatalogError(f"{aid}: missing {key}")
        apps[aid] = app
    return apps


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
