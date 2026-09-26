"""Online updates: a new PolyOS version installs from Settings, without a new ISO.

Every release on GitHub carries PolyOS's own packages (polyos-shell, polyos-desktop, ...) and
polyos-update.json, which lists them with their SHA-256 checksums:

    {"version": "0.7.1", "packages": [{"name": "polyos-shell", "file": "polyos-shell_0.7.1_all.deb",
     "sha256": "...", "size": 123456}, ...]}

check() reads the newest release (anyone can; no root). install() runs as root in polyos-admin:
it downloads the manifest and packages itself from the fixed GitHub address, checks every
checksum and name, then installs them with apt, which also brings in any new dependencies.
Debian's own updates (the rest of the system) install with `apt-get full-upgrade`.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

from . import __version__

REPO = "kingxxasavan/poly-os-7-debain-receration"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
MANIFEST = "polyos-update.json"
USER_AGENT = f"PolyOS/{__version__} (+https://github.com/{REPO})"
PACKAGE_FILE = re.compile(r"^(polyos-[a-z]+)_(\d+\.\d+\.\d+)_all\.deb$")
CACHE = Path("/var/cache/polyos-update")
MAX_BYTES = 200 * 1024 * 1024


def version_tuple(v: str) -> tuple[int, ...]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def newer(latest: str, current: str = __version__) -> bool:
    return version_tuple(latest) > version_tuple(current)


def _get(url: str, timeout: float = 20, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https addresses
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("download too large")
    return data


def parse_release(release: dict) -> dict:
    """The newest release: version, notes, when, and where its update manifest is (if it has one)."""
    assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets") or []}
    return {"version": (release.get("tag_name") or "").lstrip("v"), "notes": release.get("body") or "",
            "published": release.get("published_at") or "", "url": release.get("html_url") or "",
            "manifest": assets.get(MANIFEST), "assets": assets}


def validate_manifest(manifest: dict, assets: dict[str, str]) -> list[dict]:
    """The packages to download: known names, the manifest's version, a checksum each, and a URL."""
    version = manifest.get("version")
    packages = manifest.get("packages")
    if not isinstance(version, str) or not isinstance(packages, list) or not packages:
        raise ValueError("The update's package list is damaged.")
    out = []
    for item in packages:
        file = item.get("file") if isinstance(item, dict) else None
        m = PACKAGE_FILE.match(file or "")
        if not m or m.group(2) != version or m.group(1) != item.get("name"):
            raise ValueError(f"Unexpected package in the update: {file}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            raise ValueError(f"No checksum for {file}.")
        if file not in assets:
            raise ValueError(f"{file} is missing from the release.")
        out.append({"name": item["name"], "file": file, "sha256": item["sha256"], "url": assets[file],
                    "size": int(item.get("size") or 0)})
    return out


def check(get=_get) -> dict:
    """{current, latest, available, notes, size} for Settings > About."""
    release = parse_release(json.loads(get(LATEST_API)))
    out = {"current": __version__, "latest": release["version"], "notes": release["notes"],
           "published": release["published"], "url": release["url"], "available": False, "size": 0}
    if newer(release["version"]) and release["manifest"]:
        manifest = json.loads(get(release["manifest"]))
        packages = validate_manifest(manifest, release["assets"])
        out.update(available=True, size=sum(p["size"] for p in packages), packages=[p["name"] for p in packages])
    elif newer(release["version"]):
        out["reason"] = "This release can only be installed from its ISO."
    return out


def download(emit, get=_get, cache: Path = CACHE) -> tuple[str, list[Path]]:
    """(version, verified .deb files), for polyos-admin. Raises ValueError with a readable message."""
    release = parse_release(json.loads(get(LATEST_API)))
    if not newer(release["version"]):
        raise ValueError("PolyOS is already up to date.")
    if not release["manifest"]:
        raise ValueError("This release can only be installed from its ISO.")
    packages = validate_manifest(json.loads(get(release["manifest"])), release["assets"])
    cache.mkdir(parents=True, exist_ok=True)
    for old in cache.glob("*.deb"):
        old.unlink()
    files = []
    for n, pkg in enumerate(packages):
        emit({"progress": 0.05 + 0.4 * n / len(packages), "message": f"Downloading {pkg['name']}…"})
        data = get(pkg["url"], timeout=120, accept="application/octet-stream")
        if hashlib.sha256(data).hexdigest() != pkg["sha256"]:
            raise ValueError(f"{pkg['file']} didn't download correctly (checksum mismatch). Try again.")
        path = cache / pkg["file"]
        path.write_bytes(data)
        path.chmod(0o644)
        files.append(path)
    return release["version"], files


def build_manifest(version: str, debs: list[Path]) -> dict:
    """What the release workflow publishes as polyos-update.json."""
    items = []
    for deb in sorted(debs):
        m = PACKAGE_FILE.match(deb.name)
        if not m:
            continue
        items.append({"name": m.group(1), "file": deb.name, "size": deb.stat().st_size,
                      "sha256": hashlib.sha256(deb.read_bytes()).hexdigest()})
    import datetime
    return {"version": version, "published": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "packages": items}
