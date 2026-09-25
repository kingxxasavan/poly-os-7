"""The PolyOS installer engine: puts the live system onto a disk.

probe() and install() run as root through polyos-admin (the setup UI never touches disks
itself). Everything that decides *what* to do (reading lsblk/sfdisk/os-prober output,
finding free space, sizing partitions, validating the plan) is plain Python with no side
effects, so it is unit-tested on any OS. The steps use standard Debian tools: sfdisk,
mkfs, ntfsresize, resize2fs, unsquashfs, chroot, grub-install and efibootmgr.

Two modes:
  erase      wipe one disk: EFI system partition + ext4 root (UEFI), or one ext4 root (BIOS)
  alongside  keep the other system: use free space, or shrink its NTFS/ext4 partition first;
             GRUB then offers both (os-prober)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import recovery

KiB, MiB, GiB = 1024, 1024 ** 2, 1024 ** 3
MIN_ROOT = 20 * GiB          # smallest PolyOS partition the installer offers
SUGGESTED_ROOT = 64 * GiB    # default size when installing alongside another system
KEEP_FREE = 10 * GiB         # a shrunk system keeps at least this much free space
ESP_BYTES = 512 * MiB
BIOS_BOOT_BYTES = 1 * MiB
ALIGN = 1 * MiB

ESP_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
LINUX_GUID = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
BIOS_BOOT_GUID = "21686148-6449-6E6F-744E-656564454649"
MS_BASIC_GUID = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"
ESP_MBR_TYPES = {"ef", "0xef"}
EXTENDED_MBR_TYPES = {"5", "f", "85", "0x5", "0xf", "0x85"}

SQUASHFS = Path("/run/live/medium/live/filesystem.squashfs")
LIVE_MEDIUM = Path("/run/live/medium")
TARGET = Path("/mnt/polyos-target")
OFFLINE_DEBS = "/usr/share/polyos/installer/debs"  # efi/ and bios/: GRUB packages fetched at ISO build
LOG_PATH = Path("/var/log/polyos-installer.log")
LIVE_PACKAGES = ["live-boot", "live-boot-initramfs-tools", "live-config", "live-config-systemd", "live-tools",
                 "calamares", "calamares-settings-debian", "user-setup"]
USER_GROUPS = ["sudo", "audio", "video", "plugdev", "netdev", "bluetooth", "lpadmin", "scanner", "users", "dip", "cdrom"]
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
RESERVED_USERS = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp", "proxy", "www-data",
    "backup", "list", "irc", "nobody", "messagebus", "lightdm", "polkitd", "avahi", "colord", "pulse", "rtkit",
    "saned", "sshd", "systemd-network", "systemd-resolve", "systemd-timesync", "tss", "usbmux", "polyos", "admin",
}
LSBLK_COLUMNS = "NAME,TYPE,SIZE,MODEL,TRAN,RM,RO,FSTYPE,LABEL,PARTTYPE,PARTN,MOUNTPOINTS,PTTYPE,PKNAME"


class InstallError(Exception):
    """A failure whose message is meant for the person installing."""


# ==== reading the machine (pure parsers) ===================================================

def _align_up(value: int, step: int) -> int:
    return -(-value // step) * step


def _align_down(value: int, step: int) -> int:
    return value // step * step


def parse_lsblk(data: dict) -> list[dict]:
    """Disks from `lsblk -J -b -p -o LSBLK_COLUMNS`, with their partitions."""
    disks = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        name = dev.get("name") or ""
        if re.match(r"^/dev/(zram|loop|sr|ram|fd)", name):
            continue
        parts = []
        for child in dev.get("children") or []:
            if child.get("type") != "part":
                continue
            parts.append({
                "path": child.get("name"),
                "number": int(child["partn"]) if str(child.get("partn") or "").isdigit() else None,
                "size": int(child.get("size") or 0),
                "fstype": child.get("fstype") or "",
                "label": child.get("label") or "",
                "parttype": (child.get("parttype") or "").lower(),
                "mounts": [m for m in (child.get("mountpoints") or []) if m],
            })
        disks.append({
            "path": name,
            "size": int(dev.get("size") or 0),
            "model": (dev.get("model") or "").strip() or "Disk",
            "transport": dev.get("tran") or "",
            "removable": bool(dev.get("rm")) and dev.get("rm") not in ("0", 0),
            "readonly": bool(dev.get("ro")) and dev.get("ro") not in ("0", 0),
            "table": dev.get("pttype") or None,
            "mounts": [m for m in (dev.get("mountpoints") or []) if m],
            "partitions": parts,
        })
    return disks


def parse_sfdisk(data: dict) -> dict:
    """Geometry from `sfdisk -J DISK`: label, sector size, usable range and partitions (in sectors)."""
    table = data["partitiontable"]
    sector = int(table.get("sectorsize") or 512)
    parts = []
    for p in table.get("partitions", []):
        node = p["node"]
        m = re.search(r"(\d+)$", node)
        parts.append({"node": node, "number": int(m.group(1)) if m else None, "start": int(p["start"]),
                      "size": int(p["size"]), "type": str(p.get("type", "")).lower()})
    return {
        "label": table.get("label"),
        "sector": sector,
        "first": int(table.get("firstlba") or (ALIGN // sector)),
        "last": int(table["lastlba"]) if table.get("lastlba") is not None else None,
        "partitions": sorted(parts, key=lambda p: p["start"]),
    }


def free_regions(table: dict, disk_bytes: int) -> list[dict]:
    """Unallocated, 1 MiB-aligned gaps (in sectors) that could hold a new partition."""
    sector = table["sector"]
    align = max(1, ALIGN // sector)
    first = max(table["first"], align)
    last = table["last"] if table["last"] is not None else disk_bytes // sector - 1
    used = [p for p in table["partitions"] if p["size"] > 0]
    regions, cursor = [], first
    for p in used:  # an extended partition counts as used: new primaries go outside it
        if p["start"] > cursor:
            regions.append((cursor, p["start"] - 1))
        cursor = max(cursor, p["start"] + p["size"])
    if last >= cursor:
        regions.append((cursor, last))
    out = []
    for lo, hi in regions:
        start = _align_up(lo, align)
        end = _align_down(hi + 1, align)  # exclusive
        if end - start >= align * 16:  # ignore slivers under 16 MiB
            out.append({"start": start, "size": end - start})
    return out


def parse_os_prober(text: str) -> dict[str, str]:
    """`os-prober` lines look like /dev/sda1@/efi/Microsoft/Boot/bootmgfw.efi:Windows Boot Manager:Windows:efi."""
    found = {}
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 3:
            continue
        dev = parts[0].split("@", 1)[0]
        name = parts[1].strip() or parts[2].strip()
        if name == "Windows Boot Manager":
            name = "Windows"
        found[dev] = name
    return found


_NTFS_MIN = re.compile(r"You might resize at (\d+) bytes")


def parse_ntfsresize_info(text: str) -> tuple[int | None, str | None]:
    """(minimum size in bytes, reason it can't be resized) from `ntfsresize --info`."""
    lowered = text.lower()
    if "hibernated" in lowered or "unsafe state" in lowered or "fast restart" in lowered:
        return None, ("Windows didn't shut down completely (Fast Startup or hibernation is on). Start Windows, "
                      "turn off Fast Startup in Power Options, then shut down and try again.")
    if "bitlocker" in lowered:
        return None, "This partition is encrypted with BitLocker. Turn BitLocker off in Windows first."
    m = _NTFS_MIN.search(text)
    if m:
        return int(m.group(1)), None
    if "error" in lowered:
        last = [ln for ln in text.splitlines() if "error" in ln.lower()]
        return None, f"Windows' partition can't be resized: {last[-1].strip() if last else 'ntfsresize failed'}"
    return None, "Couldn't check how far this partition can shrink."


_RESIZE2FS_MIN = re.compile(r"Estimated minimum size of the filesystem:\s*(\d+)")
_BLOCK_SIZE = re.compile(r"^Block size:\s*(\d+)", re.M)


def parse_ext4_min(resize2fs_out: str, dumpe2fs_out: str) -> int | None:
    m = _RESIZE2FS_MIN.search(resize2fs_out)
    b = _BLOCK_SIZE.search(dumpe2fs_out)
    if not m or not b:
        return None
    return int(m.group(1)) * int(b.group(1))


def is_esp(part: dict, label: str | None) -> bool:
    ptype = part.get("parttype", "")
    return ptype == ESP_GUID.lower() or (label == "dos" and ptype in ESP_MBR_TYPES)


def guess_os(part: dict, prober: dict[str, str]) -> str | None:
    if part["path"] in prober:
        return prober[part["path"]]
    if part["fstype"] == "ntfs" and part["size"] >= 20 * GiB and part["parttype"] in (MS_BASIC_GUID.lower(), "0x7", "7"):
        return "Windows"
    if part["fstype"] == "BitLocker":
        return "Windows (BitLocker)"
    return None


def alongside_option(disk: dict, uefi: bool) -> dict:
    """How PolyOS could fit next to what's on this disk: free space, or shrinking one partition."""
    need_esp = uefi and not any(p.get("esp") for p in disk["partitions"])
    extra = (ESP_BYTES if need_esp else 0) + (BIOS_BOOT_BYTES if (not uefi and disk["table"] == "gpt") else 0)
    if disk["table"] is None:
        return {"possible": False, "reason": "This disk is empty. Choose “Install PolyOS 7” to use all of it."}
    if uefi and disk["table"] == "dos" and need_esp:
        return {"possible": False, "reason": "The system on this disk starts in legacy BIOS mode. Restart this USB "
                "drive in legacy (CSM) mode to install PolyOS next to it."}
    if not uefi and disk["table"] == "gpt" and any(p.get("esp") for p in disk["partitions"]) \
            and not any(p["parttype"] == BIOS_BOOT_GUID.lower() for p in disk["partitions"]):
        return {"possible": False, "reason": "The system on this disk starts in UEFI mode, but this USB drive "
                "started in legacy BIOS mode. Restart it in UEFI mode to install alongside."}
    if disk["table"] == "dos":
        primaries = [p for p in disk["partitions"] if (p["number"] or 0) <= 4]
        if len(primaries) >= 4:
            return {"possible": False, "reason": "This disk already has four primary partitions, the most it can hold."}
    best = None
    for region in disk.get("free", []):
        usable = region["bytes"] - extra
        if usable >= MIN_ROOT and (best is None or usable > best["maxBytes"]):
            best = {"possible": True, "kind": "free", "start": region["start"], "maxBytes": usable, "extra": extra}
    for part in disk["partitions"]:
        info = part.get("resize") or {}
        if info.get("min") is None:
            continue
        keep = _align_up(max(info["min"], (info.get("used") or info["min"]) + KEEP_FREE), ALIGN)
        usable = _align_down(part["size"] - keep, ALIGN) - extra
        if usable >= MIN_ROOT and (best is None or (best["kind"] != "free" and usable > best["maxBytes"])):
            best = {"possible": True, "kind": "shrink", "partition": part["path"], "keepMin": keep,
                    "maxBytes": usable, "extra": extra}
    if best:
        best["suggested"] = min(best["maxBytes"], max(MIN_ROOT, min(SUGGESTED_ROOT, best["maxBytes"] // 2)))
        best["minBytes"] = MIN_ROOT
        return best
    reasons = [p["resize"]["reason"] for p in disk["partitions"] if (p.get("resize") or {}).get("reason")]
    return {"possible": False, "reason": reasons[0] if reasons else
            f"There isn't enough free space. PolyOS needs at least {MIN_ROOT // GiB} GB."}


def describe_disk(disk: dict, table: dict | None, prober: dict[str, str], uefi: bool, live_disk: str | None,
                  resize: dict[str, dict]) -> dict:
    """Everything the setup UI shows about one disk."""
    label = table["label"] if table else None
    # os-prober names UEFI Windows by its boot partition; give that name to the NTFS partition too
    probed = [prober[p["path"]] for p in disk["partitions"] if p["path"] in prober]
    windows_name = next((n for n in probed if "windows" in n.lower()), None)
    for part in disk["partitions"]:
        part["esp"] = is_esp(part, label)
        part["os"] = guess_os(part, prober)
        if part["os"] == "Windows" and part["path"] not in prober and windows_name:
            part["os"] = windows_name
        part["resize"] = resize.get(part["path"])
    disk["table"] = label
    disk["free"] = [{"start": r["start"], "bytes": r["size"] * table["sector"]}
                    for r in free_regions(table, disk["size"])] if table else []
    disk["oses"] = sorted({p["os"] for p in disk["partitions"] if p["os"]})
    disk["isLive"] = disk["path"] == live_disk
    disk["canErase"] = not disk["isLive"] and not disk["readonly"] and disk["size"] >= MIN_ROOT
    disk["alongside"] = alongside_option(disk, uefi) if disk["canErase"] else \
        {"possible": False, "reason": "PolyOS is running from this drive." if disk["isLive"] else "This disk is too small."}
    return disk


# ==== the plan the setup UI sends ============================================================

def validate_plan(plan: dict, existing_users: set[str] | None = None) -> dict:
    """Check the setup UI's plan; returns a cleaned copy. Raises InstallError with a readable message."""
    if not isinstance(plan, dict):
        raise InstallError("The install plan is missing.")
    mode = plan.get("mode")
    if mode not in ("erase", "alongside"):
        raise InstallError("Choose how to install PolyOS.")
    disk = plan.get("disk")
    if not isinstance(disk, str) or not re.match(r"^/dev/[A-Za-z0-9/_-]+$", disk):
        raise InstallError("Choose a disk.")
    user = plan.get("user") or {}
    username = str(user.get("username") or "")
    if not USERNAME_RE.match(username):
        raise InstallError("Usernames use lowercase letters, numbers, - and _, and start with a letter.")
    if username in RESERVED_USERS or username in (existing_users or set()):
        raise InstallError(f"“{username}” is reserved. Pick another username.")
    full = str(user.get("fullName") or "").strip()[:80] or username
    if any(c in full for c in ":,\n="):
        raise InstallError("Your name can't contain : , or =.")
    password = user.get("password") or ""
    if not isinstance(password, str) or len(password) > 256 or "\n" in password:
        raise InstallError("That password can't be used.")
    key = user.get("recoveryKey") or ""
    if key and not recovery.looks_valid(str(key)):
        raise InstallError("The recovery key is damaged. Go back and try again.")
    hostname = str(plan.get("hostname") or f"{username}-polyos").lower()
    if not HOSTNAME_RE.match(hostname):
        raise InstallError("Computer names use letters, numbers and hyphens (up to 63).")
    tz = str(plan.get("timezone") or "UTC")
    if ".." in tz or not re.match(r"^[A-Za-z0-9_+/-]{1,64}$", tz):
        raise InstallError("Choose a time zone.")
    appearance = plan.get("appearance") or {}
    theme = appearance.get("theme") if appearance.get("theme") in ("dark", "light") else "dark"
    accent = appearance.get("accent") if re.match(r"^#[0-9a-fA-F]{6}$", str(appearance.get("accent") or "")) else "#678fd9"
    clean = {"mode": mode, "disk": disk, "hostname": hostname, "timezone": tz,
             "user": {"username": username, "fullName": full, "password": password, "recoveryKey": str(key)},
             "appearance": {"theme": theme, "accent": accent.lower()}}
    if mode == "alongside":
        size = plan.get("size")
        if not isinstance(size, int) or size < MIN_ROOT:
            raise InstallError(f"Give PolyOS at least {MIN_ROOT // GiB} GB.")
        clean["size"] = size
    return clean


def erase_script(label: str, uefi: bool) -> str:
    """sfdisk input for a whole-disk install."""
    if uefi:
        return (f"label: gpt\nsize={ESP_BYTES // MiB}MiB, type={ESP_GUID}, name=\"EFI system\"\n"
                f"type={LINUX_GUID}, name=\"PolyOS\"\n")
    if label == "gpt":  # BIOS on a disk over 2 TiB: GPT with a BIOS boot partition for GRUB
        return (f"label: gpt\nsize={BIOS_BOOT_BYTES // MiB}MiB, type={BIOS_BOOT_GUID}, name=\"BIOS boot\"\n"
                f"type={LINUX_GUID}, name=\"PolyOS\"\n")
    return "label: dos\ntype=83, bootable\n"


def alongside_layout(start: int, size_bytes: int, sector: int, label: str, need_esp: bool, need_bios: bool) -> list[dict]:
    """New partitions (in sectors) packed from `start`: [ESP] [BIOS boot] root."""
    align = max(1, ALIGN // sector)
    out, cursor = [], _align_up(start, align)
    if need_esp:
        n = ESP_BYTES // sector
        out.append({"role": "esp", "start": cursor, "size": n, "type": ESP_GUID if label == "gpt" else "ef"})
        cursor += n
    if need_bios:
        n = BIOS_BOOT_BYTES // sector
        out.append({"role": "bios", "start": cursor, "size": n, "type": BIOS_BOOT_GUID})
        cursor += n
    root = _align_down(size_bytes // sector, align)
    out.append({"role": "root", "start": cursor, "size": root, "type": LINUX_GUID if label == "gpt" else "83"})
    return out


def efi_entries(text: str) -> dict[str, str]:
    """`efibootmgr` output -> {boot number: label}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^Boot([0-9A-Fa-f]{4})\*?\s+(.+?)(?:\t|\s{2,}|\s+(?:HD|PciRoot|VenHw)\()", line)
        if m:
            out[m.group(1).upper()] = m.group(2).strip()
    return out


def fstab(root_uuid: str, esp_uuid: str | None, swapfile: bool) -> str:
    lines = ["# /etc/fstab: created by the PolyOS installer", "# <file system>  <mount point>  <type>  <options>  <dump>  <pass>",
             f"UUID={root_uuid}  /  ext4  errors=remount-ro  0  1"]
    if esp_uuid:
        lines.append(f"UUID={esp_uuid}  /boot/efi  vfat  umask=0077  0  1")
    if swapfile:
        lines.append("/swapfile  none  swap  sw  0  0")
    return "\n".join(lines) + "\n"


def swap_bytes(ram: int) -> int:
    return max(1 * GiB, min(4 * GiB, _align_up(ram, GiB)))


def partition_node(disk: str, number: int) -> str:
    """/dev/sda + 2 -> /dev/sda2; /dev/nvme0n1 + 2 -> /dev/nvme0n1p2."""
    return f"{disk}p{number}" if disk[-1].isdigit() else f"{disk}{number}"


# ==== running as root ======================================================================

Emit = Callable[[dict], None]


class Runner:
    """Runs commands, logging everything; raises InstallError on failure."""

    def __init__(self, emit: Emit, dry_run: bool = False):
        self.emit = emit
        self.dry_run = dry_run
        self.log = None if dry_run else open(LOG_PATH, "a", encoding="utf-8")  # noqa: SIM115

    def note(self, text: str) -> None:
        if self.log:
            self.log.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")
            self.log.flush()

    def run(self, args: list[str], *, input: str | None = None, check: bool = True, timeout: float = 600,
            what: str | None = None, env: dict | None = None) -> str:
        self.note("$ " + " ".join(args))
        if self.dry_run:
            self.emit({"log": "$ " + " ".join(args)})
            return ""
        try:
            proc = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout,
                                  env={**os.environ, "LC_ALL": "C", **(env or {})})
        except FileNotFoundError:
            raise InstallError(f"{args[0]} is missing from this USB drive.") from None
        except subprocess.TimeoutExpired:
            raise InstallError(f"{what or args[0]} took too long and was stopped.") from None
        if proc.stdout.strip():
            self.note(proc.stdout.strip()[-4000:])
        if proc.stderr.strip():
            self.note(proc.stderr.strip()[-4000:])
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            raise InstallError(f"{what or 'A step'} failed: {detail[-1] if detail else f'exit code {proc.returncode}'}")
        return proc.stdout


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def live_disk() -> str | None:
    """The disk the live system was started from (never offered as a target)."""
    try:
        out = subprocess.run(["findmnt", "-n", "-o", "SOURCE", str(LIVE_MEDIUM)], capture_output=True, text=True, timeout=5).stdout.strip()
        if not out:
            return None
        parent = subprocess.run(["lsblk", "-n", "-p", "-o", "PKNAME", out], capture_output=True, text=True, timeout=5).stdout.strip()
        return parent.splitlines()[0] if parent else out
    except (OSError, subprocess.SubprocessError):
        return None


def _resize_info(runner: Runner, part: dict) -> dict | None:
    if part["mounts"] or part["size"] < MIN_ROOT + KEEP_FREE:
        return None
    if part["fstype"] == "ntfs" and _have("ntfsresize"):
        proc = subprocess.run(["ntfsresize", "--info", "--force", "--no-progress-bar", part["path"]],
                              capture_output=True, text=True, timeout=120, env={**os.environ, "LC_ALL": "C"})
        minimum, reason = parse_ntfsresize_info(proc.stdout + proc.stderr)
        return {"fs": "ntfs", "min": minimum, "used": minimum, "reason": reason}
    if part["fstype"] == "ext4" and _have("resize2fs"):
        est = subprocess.run(["resize2fs", "-P", part["path"]], capture_output=True, text=True, timeout=120)
        head = subprocess.run(["dumpe2fs", "-h", part["path"]], capture_output=True, text=True, timeout=60)
        minimum = parse_ext4_min(est.stdout + est.stderr, head.stdout)
        return {"fs": "ext4", "min": minimum, "used": minimum,
                "reason": None if minimum else "Couldn't check how far this Linux partition can shrink."}
    if part["fstype"] == "BitLocker":
        return {"fs": "bitlocker", "min": None, "reason": "This partition is encrypted with BitLocker. Turn BitLocker off in Windows first."}
    return None


def _ram_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * KiB
    except OSError:
        pass
    return 4 * GiB


def probe(emit: Emit | None = None) -> dict:
    """What the setup UI needs to offer install choices (runs as root)."""
    runner = Runner(emit or (lambda _e: None), dry_run=False)
    uefi = Path("/sys/firmware/efi").is_dir()
    raw = json.loads(runner.run(["lsblk", "-J", "-b", "-p", "-o", LSBLK_COLUMNS], what="Reading disks") or "{}")
    disks = parse_lsblk(raw)
    prober = {}
    if _have("os-prober"):
        prober = parse_os_prober(runner.run(["os-prober"], check=False, timeout=180))
    live = live_disk()
    out = []
    for disk in disks:
        table = None
        if disk["table"]:
            text = runner.run(["sfdisk", "-J", disk["path"]], check=False)
            try:
                table = parse_sfdisk(json.loads(text)) if text.strip() else None
            except (ValueError, KeyError):
                table = None
        resize = {}
        if disk["path"] != live:
            for part in disk["partitions"]:
                info = _resize_info(runner, part)
                if info:
                    resize[part["path"]] = info
        out.append(describe_disk(disk, table, prober, uefi, live, resize))
    secure_boot = False
    if uefi and _have("mokutil"):
        secure_boot = "enabled" in runner.run(["mokutil", "--sb-state"], check=False).lower()
    return {"uefi": uefi, "secureBoot": secure_boot, "ram": _ram_bytes(), "disks": out,
            "minBytes": MIN_ROOT, "liveDisk": live}


class Installer:
    def __init__(self, plan: dict, emit: Emit, dry_run: bool = False):
        self.plan = plan
        self.emit = emit
        self.r = Runner(emit, dry_run)
        self.dry = dry_run
        self.uefi = Path("/sys/firmware/efi").is_dir()
        self.disk = plan["disk"]
        self.root_dev: str | None = None
        self.esp_dev: str | None = None
        self.esp_is_new = False
        self.mounted: list[Path] = []
        self.windows_alongside = False
        self.disk_info: dict | None = None

    # ---- helpers ---------------------------------------------------------------------
    def step(self, progress: float, message: str) -> None:
        self.r.note(f"== {message}")
        self.emit({"progress": round(progress, 3), "message": message})

    def chroot(self, args: list[str], **kw) -> str:
        env = {"DEBIAN_FRONTEND": "noninteractive", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin", **kw.pop("env", {})}
        return self.r.run(["chroot", str(TARGET), *args], env=env, **kw)

    def sfdisk_table(self) -> dict:
        return parse_sfdisk(json.loads(self.r.run(["sfdisk", "-J", self.disk], what="Reading the partition table")))

    def settle(self) -> None:
        self.r.run(["partx", "-u", self.disk], check=False)
        self.r.run(["udevadm", "settle", "--timeout=15"], check=False)
        if not self.dry:
            time.sleep(1)

    # ---- steps ------------------------------------------------------------------------
    def preflight(self) -> None:
        if not self.dry and not SQUASHFS.is_file():
            raise InstallError("PolyOS can only be installed from the PolyOS USB drive.")
        if self.disk == live_disk():
            raise InstallError("That's the drive PolyOS is running from. Choose another disk.")
        disks = {d["path"]: d for d in parse_lsblk(json.loads(self.r.run(["lsblk", "-J", "-b", "-p", "-o", LSBLK_COLUMNS]) or '{"blockdevices": []}'))}
        if not self.dry and self.disk not in disks:
            raise InstallError("That disk is no longer connected.")
        info = disks.get(self.disk)
        if info and info["size"] < MIN_ROOT:
            raise InstallError("That disk is too small for PolyOS.")
        self.disk_info = info
        # anything on the disk that the live system mounted (e.g. automount) must go first
        for part in (info or {}).get("partitions", []):
            for mount in part["mounts"]:
                if mount == "[SWAP]":
                    self.r.run(["swapoff", part["path"]], check=False)
                else:
                    self.r.run(["umount", "-l", mount], check=False)

    def partition_erase(self) -> None:
        self.step(0.02, "Preparing the disk…")
        size = (self.disk_info or {}).get("size", 0)
        label = "gpt" if (self.uefi or size > 2 * 1024 ** 4) else "dos"
        self.r.run(["wipefs", "-a", "-f", self.disk], what="Clearing the disk")
        self.r.run(["sfdisk", "--wipe", "always", "--wipe-partitions", "always", "-q", self.disk],
                   input=erase_script(label, self.uefi), what="Creating partitions")
        self.settle()
        if self.uefi:
            self.esp_dev, self.root_dev, self.esp_is_new = partition_node(self.disk, 1), partition_node(self.disk, 2), True
        elif label == "gpt":
            self.root_dev = partition_node(self.disk, 2)
        else:
            self.root_dev = partition_node(self.disk, 1)

    def partition_alongside(self) -> None:
        want = self.plan["size"]
        disk = self.disk_info or {}
        table = self.sfdisk_table() if not self.dry else {"label": "gpt", "sector": 512, "first": 2048, "last": None, "partitions": []}
        sector = table["sector"]
        # rebuild the same option the UI saw, from fresh data
        resize = {}
        for part in disk.get("partitions", []):
            info = _resize_info(self.r, part) if not self.dry else None
            if info:
                resize[part["path"]] = info
        described = describe_disk(json.loads(json.dumps(disk)), table, {}, self.uefi, None, resize) if disk else None
        option = described["alongside"] if described else {"possible": False, "reason": "Disk not found."}
        if not option.get("possible"):
            raise InstallError(option.get("reason") or "There's no room for PolyOS on that disk.")
        if want > option["maxBytes"]:
            raise InstallError("That's more space than this disk can give PolyOS. Pick a smaller size.")
        existing_esp = next((p for p in described["partitions"] if p["esp"]), None)
        self.windows_alongside = any("windows" in (o or "").lower() for o in described["oses"])

        if option["kind"] == "shrink":
            part = next(p for p in described["partitions"] if p["path"] == option["partition"])
            info = part["resize"]
            new_bytes = _align_down(part["size"] - want - option["extra"], ALIGN)
            if new_bytes < option["keepMin"]:
                raise InstallError("That would leave the other system too little room.")
            self.step(0.02, f"Making room: shrinking {part['os'] or 'the other system'}…")
            if info["fs"] == "ntfs":
                self.r.run(["ntfsresize", "--no-action", "--force", "--size", str(new_bytes), part["path"]],
                           input="y\n", what="Checking Windows' partition", timeout=1800)
                self.r.run(["ntfsresize", "--force", "--no-progress-bar", "--size", str(new_bytes), part["path"]],
                           input="y\n", what="Shrinking Windows' partition", timeout=7200)
            else:
                self.r.run(["e2fsck", "-f", "-y", part["path"]], what="Checking the Linux partition", timeout=3600)
                self.r.run(["resize2fs", part["path"], f"{new_bytes // KiB}K"], what="Shrinking the Linux partition", timeout=7200)
            number = part["number"]
            self.r.run(["sfdisk", "--no-reread", "--force", "-q", "-N", str(number), self.disk],
                       input=f", {new_bytes // sector}\n", what="Resizing the partition")
            self.settle()
            table = self.sfdisk_table() if not self.dry else table
            shrunk = next((p for p in table["partitions"] if p["number"] == number), None)
            region_start = (shrunk["start"] + shrunk["size"]) if shrunk else 0
            region = next((r for r in free_regions(table, disk.get("size", 0)) if r["start"] >= region_start), None)
        else:
            region = next((r for r in free_regions(table, disk.get("size", 0)) if r["start"] == option["start"]), None)
        if region is None and not self.dry:
            raise InstallError("The free space for PolyOS disappeared. Nothing else was changed.")
        start = region["start"] if region else 2048
        need_esp = self.uefi and existing_esp is None
        need_bios = (not self.uefi) and table["label"] == "gpt"
        layout = alongside_layout(start, want, sector, table["label"], need_esp, need_bios)
        if region and sum(p["size"] for p in layout) + (layout[0]["start"] - start) > region["size"]:
            raise InstallError("PolyOS doesn't fit in the free space. Pick a smaller size.")
        self.step(0.05, "Creating PolyOS's partition…")
        before = {p["start"] for p in table["partitions"]}
        for spec in layout:
            self.r.run(["sfdisk", "--append", "--no-reread", "--force", "-q", self.disk],
                       input=f"start={spec['start']}, size={spec['size']}, type={spec['type']}\n", what="Creating partitions")
        self.settle()
        if self.dry:
            self.root_dev, self.esp_dev = partition_node(self.disk, 9), existing_esp["path"] if existing_esp else None
            return
        after = {p["start"]: p for p in self.sfdisk_table()["partitions"]}
        for spec in layout:
            created = after.get(spec["start"])
            if created is None or created["start"] in before:
                raise InstallError("The new partition didn't appear. Nothing was installed.")
            if spec["role"] == "root":
                self.root_dev = created["node"]
            elif spec["role"] == "esp":
                self.esp_dev, self.esp_is_new = created["node"], True
        if existing_esp and not self.esp_dev:
            self.esp_dev = existing_esp["path"]

    def format_and_mount(self) -> None:
        self.step(0.07, "Formatting…")
        self.r.run(["mkfs.ext4", "-F", "-q", "-L", "PolyOS", self.root_dev], what="Formatting the PolyOS partition")
        if self.esp_dev and self.esp_is_new:
            self.r.run(["mkfs.vfat", "-F", "32", "-n", "EFI", self.esp_dev], what="Formatting the EFI partition")
        if not self.dry:
            TARGET.mkdir(parents=True, exist_ok=True)
        self.r.run(["mount", self.root_dev, str(TARGET)], what="Mounting the new system")
        self.mounted.append(TARGET)
        if self.esp_dev:
            esp_mount = TARGET / "boot" / "efi"
            if not self.dry:
                esp_mount.mkdir(parents=True, exist_ok=True)
            self.r.run(["mount", self.esp_dev, str(esp_mount)], what="Mounting the EFI partition")
            self.mounted.append(esp_mount)

    def copy_system(self) -> None:
        self.step(0.09, "Copying PolyOS to the disk…")
        args = ["unsquashfs", "-f", "-d", str(TARGET), "-percentage", str(SQUASHFS)]
        self.r.note("$ " + " ".join(args))
        if self.dry:
            return
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        last = -1
        tail: list[str] = []
        for line in proc.stdout:
            line = line.strip()
            if line.isdigit():
                pct = int(line)
                if pct != last:
                    last = pct
                    self.emit({"progress": round(0.09 + 0.6 * pct / 100, 3), "message": f"Copying PolyOS to the disk… {pct}%"})
            elif line:
                tail = (tail + [line])[-20:]
        if proc.wait() != 0:
            self.r.note("\n".join(tail))
            raise InstallError("Copying PolyOS failed. The USB drive may be damaged; try writing it again.")

    def configure(self) -> None:
        self.step(0.70, "Setting up your computer…")
        plan = self.plan
        write = self._write
        root_uuid = self._uuid(self.root_dev)
        esp_uuid = self._uuid(self.esp_dev) if self.esp_dev else None
        swap = swap_bytes(_ram_bytes())
        if not self.dry:
            self.r.run(["fallocate", "-l", str(swap), str(TARGET / "swapfile")], what="Creating the swap file")
            os.chmod(TARGET / "swapfile", 0o600)
            self.r.run(["mkswap", str(TARGET / "swapfile")], what="Creating the swap file")
        write("etc/fstab", fstab(root_uuid, esp_uuid, swapfile=True))
        host = plan["hostname"]
        write("etc/hostname", host + "\n")
        write("etc/hosts", f"127.0.0.1\tlocalhost\n127.0.1.1\t{host}\n\n::1\tlocalhost ip6-localhost ip6-loopback\n"
                           "ff02::1\tip6-allnodes\nff02::2\tip6-allrouters\n")
        tz = plan["timezone"]
        if not self.dry and not (Path("/usr/share/zoneinfo") / tz).is_file():
            tz = "UTC"
        write("etc/timezone", tz + "\n")
        if not self.dry:
            localtime = TARGET / "etc/localtime"
            localtime.unlink(missing_ok=True)
            localtime.symlink_to(f"/usr/share/zoneinfo/{tz}")
        if self.windows_alongside:  # Windows keeps the hardware clock in local time
            write("etc/adjtime", "0.0 0 0.0\n0\nLOCAL\n")
        write("etc/default/locale", "LANG=en_US.UTF-8\n")
        if not self.dry:
            gen = TARGET / "etc/locale.gen"
            text = gen.read_text() if gen.exists() else ""
            if not re.search(r"^en_US\.UTF-8 UTF-8", text, re.M):
                gen.write_text(re.sub(r"^# ?en_US\.UTF-8 UTF-8", "en_US.UTF-8 UTF-8", text, flags=re.M)
                               if "en_US.UTF-8 UTF-8" in text else text + "en_US.UTF-8 UTF-8\n")
            (TARGET / "etc/machine-id").write_text("")  # a fresh id on first boot
            (TARGET / "var/lib/dbus/machine-id").unlink(missing_ok=True)
            # Wi-Fi networks joined during setup keep working after the restart
            src = Path("/etc/NetworkManager/system-connections")
            dst = TARGET / "etc/NetworkManager/system-connections"
            if src.is_dir() and dst.parent.is_dir():
                dst.mkdir(mode=0o700, exist_ok=True)
                for conn in src.glob("*.nmconnection"):
                    shutil.copy2(conn, dst / conn.name)
                    os.chmod(dst / conn.name, 0o600)

    def _write(self, rel: str, text: str) -> None:
        self.r.note(f"write /{rel}")
        if self.dry:
            return
        path = TARGET / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def _uuid(self, dev: str | None) -> str:
        if self.dry:
            return "0000-DRYRUN"
        out = self.r.run(["blkid", "-s", "UUID", "-o", "value", dev], what="Reading a partition id").strip()
        if not out:
            raise InstallError(f"{dev} has no filesystem id.")
        return out

    def bind_mounts(self) -> None:
        for src in ("dev", "dev/pts", "proc", "sys", "run"):
            dst = TARGET / src
            if not self.dry:
                dst.mkdir(parents=True, exist_ok=True)
            flag = "--rbind" if src == "sys" else "--bind"
            self.r.run(["mount", flag, f"/{src}", str(dst)], what=f"Preparing /{src}")
            self.mounted.append(dst)
        self._write("usr/sbin/policy-rc.d", "#!/bin/sh\nexit 101\n")  # no services start inside the chroot
        if not self.dry:
            os.chmod(TARGET / "usr/sbin/policy-rc.d", 0o755)

    def packages(self) -> None:
        self.step(0.74, "Removing the live-system tools…")
        installed = set(self.chroot(["dpkg-query", "-W", "-f", "${Package}\n"], check=False).split())
        remove = [p for p in LIVE_PACKAGES if p in installed] if not self.dry else LIVE_PACKAGES
        if remove:
            self.chroot(["apt-get", "-y", "purge", *remove], what="Removing live-system packages", timeout=900)
            self.chroot(["apt-get", "-y", "autoremove", "--purge"], check=False, timeout=900)
        self.chroot(["locale-gen"], check=False, timeout=300)

    def create_user(self) -> None:
        self.step(0.80, "Creating your account…")
        user = self.plan["user"]
        name = user["username"]
        existing = set()
        if not self.dry:
            existing = {ln.split(":", 1)[0] for ln in (TARGET / "etc/passwd").read_text().splitlines() if ln}
            groups_file = {ln.split(":", 1)[0] for ln in (TARGET / "etc/group").read_text().splitlines() if ln}
        else:
            groups_file = set(USER_GROUPS)
        if name in existing:
            raise InstallError(f"The username “{name}” is already used by the system. Pick another.")
        groups = ",".join(g for g in USER_GROUPS if g in groups_file)
        self.chroot(["useradd", "-m", "-s", "/bin/bash", "-c", user["fullName"], "-G", groups, name], what="Creating your account")
        if user["password"]:
            self.chroot(["chpasswd"], input=f"{name}:{user['password']}\n", what="Setting your password")
        else:
            self.chroot(["passwd", "-d", name], what="Setting up sign-in without a password")
            self._write("etc/lightdm/lightdm.conf.d/60-polyos-autologin.conf",
                        f"# The account was created without a password: sign in automatically.\n[Seat:*]\n"
                        f"autologin-user={name}\nautologin-session=polyos\n")
        self._write(f"var/lib/AccountsService/users/{name}", "[User]\nSession=polyos\nXSession=polyos\nSystemAccount=false\n")
        if user.get("recoveryKey") and not self.dry:  # only its hash is stored
            recovery.save_record(name, recovery.make_record(user["recoveryKey"]), root=TARGET)
        # PolyOS settings from the setup screens, plus the wallpapers in Pictures
        appearance = self.plan["appearance"]
        settings = {"theme": appearance["theme"], "accent": appearance["accent"], "setupDone": False}
        home = f"home/{name}"
        self._write(f"{home}/.config/polyos/settings.json", json.dumps(settings, indent=2) + "\n")
        if not self.dry:
            walls = Path("/usr/share/polyos/wallpapers")
            pics = TARGET / home / "Pictures" / "Wallpapers"
            pics.mkdir(parents=True, exist_ok=True)
            for wall in walls.glob("*.jpg") if walls.is_dir() else []:
                shutil.copy2(wall, pics / wall.name)
        self.chroot(["chown", "-R", f"{name}:{name}", f"/{home}"], what="Setting up your home folder")

    def bootloader(self) -> None:
        self.step(0.86, "Installing the boot loader…")
        dual = self.plan["mode"] == "alongside"
        self._write("etc/default/grub",
                    "# Written by the PolyOS installer. Run update-grub after editing.\n"
                    "GRUB_DEFAULT=0\n"
                    f"GRUB_TIMEOUT={10 if dual else 2}\n"
                    f"GRUB_TIMEOUT_STYLE={'menu' if dual else 'hidden'}\n"
                    'GRUB_DISTRIBUTOR="PolyOS"\n'
                    'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
                    'GRUB_CMDLINE_LINUX=""\n'
                    f"GRUB_DISABLE_OS_PROBER={'false' if dual else 'true'}\n")
        debs = []
        if not self.dry:
            kind = "efi" if self.uefi else "bios"
            folder = TARGET / OFFLINE_DEBS.lstrip("/") / kind
            debs = [f"{OFFLINE_DEBS}/{kind}/{p.name}" for p in sorted(folder.glob("*.deb"))]
        if not self.uefi:
            by_id = self._by_id(self.disk)
            self.chroot(["debconf-set-selections"], input=f"grub-pc grub-pc/install_devices multiselect {by_id}\n", check=False)
        if debs:
            self.chroot(["dpkg", "-i", *debs], check=False, what="Installing GRUB", timeout=600)
        if self.uefi:
            signed = self.dry or (TARGET / "usr/lib/shim/shimx64.efi.signed").exists()
            args = ["grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi", "--bootloader-id=debian", "--recheck",
                    "--uefi-secure-boot" if signed else "--no-uefi-secure-boot"]
            if not dual:
                args.append("--force-extra-removable")  # for firmware that ignores boot entries
            self.chroot(args, what="Installing the boot loader", timeout=600)
            self._efi_label()
        else:
            self.chroot(["grub-install", "--target=i386-pc", "--recheck", self.disk], what="Installing the boot loader", timeout=600)
        self.step(0.92, "Finishing the boot menu…")
        self.chroot(["update-initramfs", "-u", "-k", "all"], what="Building the startup image", timeout=900)
        self.chroot(["update-grub"], what="Creating the boot menu", timeout=900)
        if not self.dry:
            shutil.rmtree(TARGET / OFFLINE_DEBS.lstrip("/"), ignore_errors=True)

    def _by_id(self, disk: str) -> str:
        folder = Path("/dev/disk/by-id")
        if folder.is_dir():
            for link in sorted(folder.iterdir()):
                if link.name.startswith(("ata-", "nvme-", "scsi-", "mmc-", "usb-")) and "-part" not in link.name:
                    try:
                        if os.path.realpath(link) == os.path.realpath(disk):
                            return str(link)
                    except OSError:
                        continue
        return disk

    def _efi_label(self) -> None:
        """Show "PolyOS" in the firmware boot menu (grub-install names its entry "debian")."""
        if not _have("efibootmgr") or not self.esp_dev:
            return
        entries = efi_entries(self.r.run(["efibootmgr"], check=False))
        number = next((p["number"] for p in (self.disk_info or {}).get("partitions", []) if p["path"] == self.esp_dev), None)
        if number is None:
            m = re.search(r"(\d+)$", self.esp_dev)
            number = int(m.group(1)) if m else 1
        for num, label in entries.items():
            if label == "PolyOS":
                self.r.run(["efibootmgr", "-q", "-b", num, "-B"], check=False)
        loader = "\\EFI\\debian\\shimx64.efi" if (self.dry or (TARGET / "boot/efi/EFI/debian/shimx64.efi").exists()) \
            else "\\EFI\\debian\\grubx64.efi"
        self.r.run(["efibootmgr", "-q", "-c", "-d", self.disk, "-p", str(number), "-L", "PolyOS", "-l", loader], check=False)
        if self.dry or "PolyOS" in efi_entries(self.r.run(["efibootmgr"], check=False)).values():
            for num, label in entries.items():
                if label.lower() == "debian":
                    self.r.run(["efibootmgr", "-q", "-b", num, "-B"], check=False)

    def cleanup(self) -> None:
        if not self.dry:
            (TARGET / "usr/sbin/policy-rc.d").unlink(missing_ok=True)
            try:
                log_copy = TARGET / "var/log/polyos-installer.log"
                if LOG_PATH.exists() and log_copy.parent.is_dir():
                    shutil.copy2(LOG_PATH, log_copy)
                    os.chmod(log_copy, 0o600)
            except OSError:
                pass
        self.unmount()
        self.r.run(["sync"], check=False)

    def unmount(self) -> None:
        for path in reversed(self.mounted):
            self.r.run(["umount", "-R", "-l", str(path)], check=False)
        self.mounted.clear()

    def run(self) -> None:
        try:
            self.preflight()
            if self.plan["mode"] == "erase":
                self.partition_erase()
            else:
                self.partition_alongside()
            if not self.root_dev:
                raise InstallError("PolyOS's partition wasn't created.")
            self.format_and_mount()
            self.copy_system()
            self.configure()
            self.bind_mounts()
            self.packages()
            self.create_user()
            self.bootloader()
            self.step(0.97, "Cleaning up…")
            self.cleanup()
            self.emit({"progress": 1.0, "message": "PolyOS is installed.", "done": True})
        except InstallError:
            self.unmount()
            raise
        except Exception as exc:  # noqa: BLE001 - anything unexpected still ends with a clean unmount
            self.r.note(f"unexpected error: {exc!r}")
            self.unmount()
            raise InstallError(f"Something unexpected went wrong ({exc}). Details are in {LOG_PATH}.") from exc
