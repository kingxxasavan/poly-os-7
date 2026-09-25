"""polyos-admin: the only part of PolyOS that runs as root.

    polyos-admin probe                     disks and systems for the installer (JSON)
    polyos-admin install PLAN [--dry-run]  install PolyOS (PLAN: JSON file from the setup UI, deleted after reading)
    polyos-admin store install|remove ID   an app from the PolyMarket catalog
    polyos-admin drivers PACKAGE...        driver packages (names must match drivers.DRIVER_PACKAGE_RE)

Every command prints JSON lines: {"progress": 0..1, "message": "..."} while it works,
{"result": ...} for data, and {"error": "..."} (exit status 1) when it fails.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import drivers, installer, store

APT_ENV = {"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
APT_OPTS = ["-o", "APT::Status-Fd=1", "-o", "Dpkg::Use-Pty=0", "-o", "DPkg::Lock::Timeout=180",
            "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"]


class AdminError(Exception):
    pass


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def parse_apt_status(line: str) -> tuple[float, str] | None:
    """APT::Status-Fd lines: dlstatus:<n>:<percent>:<text> (download) / pmstatus:<pkg>:<percent>:<text> (install)."""
    parts = line.split(":", 3)
    if len(parts) < 4 or parts[0] not in ("dlstatus", "pmstatus"):
        return None
    try:
        pct = float(parts[2])
    except ValueError:
        return None
    if parts[0] == "dlstatus":
        return 0.1 + 0.4 * pct / 100, "Downloading…"
    return 0.5 + 0.48 * pct / 100, re.sub(r"^(Installing|Preparing|Unpacking|Configuring)\s+", r"\1 ", parts[3]).strip()[:120]


def _apt_error(tail: list[str]) -> str:
    text = "\n".join(tail)
    if "Could not resolve" in text or "Temporary failure resolving" in text or "Failed to fetch" in text:
        return "Couldn't reach the Debian servers. Check your internet connection and try again."
    if "Could not get lock" in text or "Unable to acquire the dpkg" in text:
        return "Another installation is running. Try again in a few minutes."
    if "Unable to locate package" in text or "has no installation candidate" in text:
        return "That package isn't available from Debian right now."
    if "No space left" in text:
        return "There isn't enough free disk space."
    errors = [ln for ln in tail if ln.startswith("E:")]
    return errors[-1][2:].strip() if errors else "The installation didn't finish."


def apt(args: list[str], start: float = 0.0) -> None:
    tail: list[str] = []
    proc = subprocess.Popen(["apt-get", "-y", *APT_OPTS, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env={**os.environ, **APT_ENV}, bufsize=1)
    for line in proc.stdout:
        line = line.rstrip()
        status = parse_apt_status(line)
        if status:
            emit({"progress": max(start, status[0]), "message": status[1]})
        elif line:
            tail = (tail + [line])[-60:]
    if proc.wait() != 0:
        raise AdminError(_apt_error(tail))


def apt_update() -> None:
    emit({"progress": 0.02, "message": "Checking Debian for the latest versions…"})
    proc = subprocess.run(["apt-get", "-q", "update", "-o", "DPkg::Lock::Timeout=180"], capture_output=True, text=True,
                          env={**os.environ, **APT_ENV}, timeout=600)
    if proc.returncode != 0 or "Failed to fetch" in proc.stdout + proc.stderr:
        raise AdminError(_apt_error((proc.stdout + proc.stderr).splitlines()))


_PERCENT = re.compile(r"(\d{1,3})%")


def flatpak(args: list[str]) -> None:
    if not shutil.which("flatpak"):
        raise AdminError("Flatpak isn't installed, so Flathub apps can't be added.")
    tail: list[str] = []
    proc = subprocess.Popen(["flatpak", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env={**os.environ, "LC_ALL": "C"}, bufsize=1)
    for line in proc.stdout:  # universal newlines split flatpak's \r progress updates
        line = line.strip()
        if not line:
            continue
        m = _PERCENT.search(line)
        if m:
            emit({"progress": 0.1 + 0.88 * min(100, int(m.group(1))) / 100, "message": line[:120]})
        tail = (tail + [line])[-40:]
    if proc.wait() != 0:
        text = "\n".join(tail)
        if "Could not resolve" in text or "Unable to connect" in text or "Couldn't connect" in text:
            raise AdminError("Couldn't reach Flathub. Check your internet connection and try again.")
        if "No space left" in text:
            raise AdminError("There isn't enough free disk space.")
        errs = [ln for ln in tail if "error" in ln.lower()]
        raise AdminError(errs[-1] if errs else "Flathub couldn't install that app.")


def store_action(action: str, app_id: str) -> None:
    apps = store.validate(store.load())
    app = apps.get(app_id)
    if app is None:
        raise AdminError("That app isn't in PolyMarket.")
    if action == "install":
        if app["source"] == "debian":
            apt_update()
            apt(["install", *app["packages"]], start=0.1)
        else:
            emit({"progress": 0.03, "message": "Connecting to Flathub…"})
            flatpak(["remote-add", "--if-not-exists", "--system", "flathub", store.FLATHUB_URL])
            flatpak(["install", "--system", "-y", "--noninteractive", "flathub", app["ref"]])
    elif action == "remove":
        if app.get("system"):
            raise AdminError(f"{app['name']} is part of PolyOS and can't be removed.")
        if app["source"] == "debian":
            apt(["remove", *app["packages"]])
            apt(["autoremove"], start=0.9)
        else:
            flatpak(["uninstall", "--system", "-y", "--noninteractive", app["ref"]])
    else:
        raise AdminError("Unknown store action.")
    emit({"progress": 1.0, "message": "Done."})


def drivers_install(packages: list[str]) -> None:
    bad = [p for p in packages if not drivers.DRIVER_PACKAGE_RE.match(p)]
    if bad or not packages:
        raise AdminError(f"Not a driver package: {', '.join(bad) or '(none)'}")
    apt_update()
    apt(["install", *packages], start=0.1)
    if any(p.startswith(("nvidia", "broadcom-sta")) or p == "linux-headers-amd64" for p in packages):
        emit({"restart": True, "message": "Restart to start using the new driver."})
    emit({"progress": 1.0, "message": "Drivers installed."})


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        emit({"error": "polyos-admin must run as root (through sudo)."})
        return 1
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "probe":
            emit({"result": installer.probe(emit)})
        elif cmd == "install":
            if not rest:
                raise AdminError("No install plan given.")
            plan_path = Path(rest[0])
            try:
                plan = json.loads(plan_path.read_text("utf-8"))
            finally:
                plan_path.unlink(missing_ok=True)  # it holds the new account's password
            installer.Installer(installer.validate_plan(plan), emit, dry_run="--dry-run" in rest).run()
        elif cmd == "store" and len(rest) == 2:
            store_action(rest[0], rest[1])
        elif cmd == "drivers":
            drivers_install(rest)
        else:
            raise AdminError(f"Unknown command: {' '.join(argv)}")
        return 0
    except (AdminError, installer.InstallError, store.CatalogError) as exc:
        emit({"error": str(exc)})
        return 1
    except subprocess.TimeoutExpired:
        emit({"error": "That took too long and was stopped."})
        return 1


if __name__ == "__main__":
    sys.exit(main())
