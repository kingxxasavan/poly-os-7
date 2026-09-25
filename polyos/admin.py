"""polyos-admin: the only part of PolyOS that runs as root.

    polyos-admin probe                     disks and systems for the installer (JSON)
    polyos-admin install PLAN [--dry-run]  install PolyOS (PLAN: JSON file from the setup UI, deleted after reading)
    polyos-admin store install|remove ID   an app from the PolyMarket catalog
    polyos-admin drivers PACKAGE...        driver packages (names must match drivers.DRIVER_PACKAGE_RE)
    polyos-admin account FILE              for the sudo user: {"password"} and/or {"recoveryKey"} (file deleted)
    polyos-admin reboot                    restart right away (after installing, from the live USB)

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

from . import drivers, installer, recovery, store

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


_HOST = re.compile(r"(?:Could not resolve|Temporary failure resolving) '([^']+)'|Failed to fetch https?://([^/\s]+)")


def _apt_error(tail: list[str]) -> str:
    """A readable message from apt's last lines, naming the server or the real error."""
    text = "\n".join(tail)
    if "Could not get lock" in text or "Unable to acquire the dpkg" in text:
        return "Another installation is running. Try again in a few minutes."
    if "No space left" in text:
        return "There isn't enough free disk space."
    if "Unable to locate package" in text or "has no installation candidate" in text:
        return "That package isn't available from Debian right now. Try again later."
    if "not valid yet" in text or "is not valid yet" in text:
        return "The computer's clock is wrong, so Debian's servers were refused. Fix the date and time, then try again."
    host = _HOST.search(text)
    if host and ("Temporary failure resolving" in text or "Could not resolve" in text or "Could not connect" in text
                 or "Connection timed out" in text or "Network is unreachable" in text):
        return (f"Couldn't reach {host.group(1) or host.group(2)}. Check your internet connection and try again.")
    errors = [ln[2:].strip() for ln in tail if ln.startswith("E:")]
    return errors[-1] if errors else "The installation didn't finish."


def _have_package_lists() -> bool:
    lists = Path("/var/lib/apt/lists")
    return lists.is_dir() and any(lists.glob("*_Packages*"))


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
    """Refresh apt's package lists. A single failed source (a mirror hiccup, deb-src, a 404) isn't fatal:
    the install that follows says what's really missing. Only stop when nothing could be downloaded."""
    emit({"progress": 0.02, "message": "Checking Debian for the latest versions…"})
    proc = subprocess.run(["apt-get", "-q", "update", "-o", "DPkg::Lock::Timeout=180"], capture_output=True, text=True,
                          env={**os.environ, **APT_ENV}, timeout=600)
    lines = (proc.stdout + proc.stderr).splitlines()
    if proc.returncode == 0 and not any(ln.startswith(("E:", "Err:")) for ln in lines):
        return
    emit({"log": "apt-get update: " + " | ".join(ln for ln in lines if ln.startswith(("E:", "W:", "Err:")))[:2000]})
    if not _have_package_lists():
        raise AdminError(_apt_error(lines[-60:]))


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


def account(path: Path) -> None:
    """Change the invoking person's password and/or recovery key (they unlocked sudo with their password)."""
    user = os.environ.get("SUDO_USER", "")
    if not user or user == "root":
        raise AdminError("Run this from your own account.")
    try:
        request = json.loads(path.read_text("utf-8"))
    finally:
        path.unlink(missing_ok=True)
    password = request.get("password")
    key = request.get("recoveryKey")
    if password is not None:
        if not isinstance(password, str) or not password or len(password) > 256 or "\n" in password:
            raise AdminError("Choose a new password.")
        proc = subprocess.run(["chpasswd"], input=f"{user}:{password}\n", capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise AdminError("The password couldn't be changed.")
    if key is not None:
        if not recovery.looks_valid(str(key)):
            raise AdminError("That recovery key is damaged.")
        recovery.save_record(user, recovery.make_record(str(key)))
    emit({"progress": 1.0, "message": "Saved."})


def reboot() -> None:
    """Restart now, without waiting on services (the install is already synced to disk)."""
    if not installer.LIVE_MEDIUM.exists():
        raise AdminError("This only works from the PolyOS USB drive.")
    subprocess.run(["sync"], check=False)
    subprocess.Popen(["systemctl", "reboot", "--force"], start_new_session=True)
    emit({"progress": 1.0, "message": "Restarting…"})


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
        elif cmd == "account" and len(rest) == 1:
            account(Path(rest[0]))
        elif cmd == "reboot":
            reboot()
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
