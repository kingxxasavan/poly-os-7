"""Driver Manager: finds the hardware and the Debian packages that make it work best.

Debian already includes open drivers for most hardware; what people usually miss is
firmware, NVIDIA's driver, video acceleration and a few Wi-Fi chips. scan() reads
`lspci -vmmnnk` (and `isenkram-lookup` / `nvidia-detect` when they're installed) and
returns one entry per device with the packages to install. Installing goes through
polyos-admin, which accepts only package names matching DRIVER_PACKAGE_RE.
"""

from __future__ import annotations

import re
import shutil
import subprocess

# Anything the Driver Manager may ask polyos-admin to install.
DRIVER_PACKAGE_RE = re.compile(
    r"^(firmware-[a-z0-9.+-]+|nvidia-driver|nvidia-tesla-\d+-driver|nvidia-open-kernel-dkms|nvidia-kernel-dkms|"
    r"linux-headers-(amd64|arm64)|broadcom-sta-dkms|mesa-vulkan-drivers|mesa-va-drivers|mesa-vdpau-drivers|libgl1-mesa-dri|"
    r"intel-media-va-driver-non-free|intel-media-va-driver|i965-va-driver|va-driver-all|vdpau-driver-all|"
    r"xserver-xorg-video-(amdgpu|ati|intel|nouveau)|intel-microcode|amd64-microcode|bluez-firmware|"
    r"nvidia-vaapi-driver|nvidia-settings|vulkan-tools|mesa-utils|"
    # touchscreens, pens and 2-in-1s; webcams and Intel IPU6 laptop cameras
    r"onboard|matchbox-keyboard|iio-sensor-proxy|xserver-xorg-input-wacom|xserver-xorg-input-libinput|"
    r"v4l-utils|gstreamer1.0-plugins-good|libcamera-ipa|libcamera-tools|gstreamer1.0-libcamera|pipewire-libcamera)$"
)

# Intel IPU6 image processors: the MIPI cameras in many 2021+ Intel laptops (Dell XPS, Lenovo
# ThinkPad X1, HP Spectre...). Not USB webcams, so they need firmware and libcamera.
IPU6_IDS = {"9a19", "9a39", "4e19", "465d", "462e", "a75d", "7d19"}

INPUT_PROP_DIRECT = 1 << 1  # a touchscreen or pen tablet: touches land where you point

# Broadcom Wi-Fi chips that only work with the proprietary "wl" driver (broadcom-sta-dkms).
BROADCOM_WL_IDS = {"4311", "4312", "4313", "4315", "4328", "4329", "432a", "432b", "432c", "432d", "4331",
                   "4353", "4357", "4358", "4359", "4360", "4365", "43a0", "43b1"}

VENDORS = {"10de": "nvidia", "1002": "amd", "8086": "intel", "14e4": "broadcom", "10ec": "realtek",
           "168c": "atheros", "17cb": "qualcomm", "14c3": "mediatek", "1b21": "asmedia", "1217": "o2micro"}

_FIELD = re.compile(r"^(\w+):\s*(.*)$")
_BRACKET = re.compile(r"^(.*?)\s*\[([0-9a-fA-F]{4})\]$")


def _split(value: str) -> tuple[str, str]:
    m = _BRACKET.match(value.strip())
    return (m.group(1).strip(), m.group(2).lower()) if m else (value.strip(), "")


def parse_lspci(text: str) -> list[dict]:
    """Records from `lspci -vmmnnk`."""
    devices, cur = [], {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur.get("slot"):
                devices.append(cur)
            cur = {}
            continue
        m = _FIELD.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if key == "Slot":
            cur["slot"] = value.strip()
        elif key == "Class":
            cur["className"], cur["classId"] = _split(value)
        elif key == "Vendor":
            cur["vendor"], cur["vendorId"] = _split(value)
        elif key == "Device":
            cur["device"], cur["deviceId"] = _split(value)
        elif key == "SDevice":
            cur["product"] = _split(value)[0]
        elif key == "Driver":
            cur["driver"] = value.strip()
        elif key == "Module":
            cur.setdefault("modules", []).append(value.strip())
    return devices


def parse_nvidia_detect(text: str) -> str | None:
    """The package nvidia-detect recommends, e.g. "nvidia-driver" or "nvidia-tesla-535-driver"."""
    m = re.search(r"install the\s+(nvidia-[a-z0-9-]+)\s+package", text.replace("\n", " "))
    if m and DRIVER_PACKAGE_RE.match(m.group(1)):
        return m.group(1)
    return None


def kind_of(dev: dict) -> str:
    cls = dev.get("classId", "")
    if cls.startswith("03"):
        return "graphics"
    if cls == "0280":
        return "wifi"
    if cls.startswith("02"):
        return "network"
    if cls.startswith("04"):
        return "audio"
    if cls == "0d11" or "bluetooth" in dev.get("device", "").lower():
        return "bluetooth"
    return "other"


def _short_vendor(dev: dict) -> str:
    name = VENDORS.get(dev.get("vendorId", ""))
    return {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel", "broadcom": "Broadcom", "realtek": "Realtek",
            "atheros": "Qualcomm Atheros", "qualcomm": "Qualcomm", "mediatek": "MediaTek"}.get(name or "", dev.get("vendor", ""))


def recommend(devices: list[dict], nvidia_pkg: str | None = None, isenkram: list[str] | None = None,
              arch: str | None = None) -> list[dict]:
    """One entry per interesting device: what it is, whether it works, and what to install."""
    from .arch import debian_arch

    arch = arch or debian_arch()
    headers = f"linux-headers-{arch}"  # for drivers built on this computer (NVIDIA, Broadcom wl)
    out = []
    for dev in devices:
        kind = kind_of(dev)
        vendor = VENDORS.get(dev.get("vendorId", ""), "")
        packages: list[str] = []
        note = None
        title = f"{_short_vendor(dev)} {dev.get('device', '')}".strip()
        if kind == "graphics":
            if vendor == "nvidia":
                pkg = nvidia_pkg or "nvidia-driver"
                packages = [headers, pkg, "firmware-misc-nonfree"]
                note = ("NVIDIA's own driver gives the best speed for games and video. Restart after installing. "
                        "With Secure Boot on, you'll be asked to enroll a key at the next start (or turn Secure Boot off).")
            elif vendor == "amd":
                packages = ["firmware-amd-graphics", "mesa-vulkan-drivers", "mesa-va-drivers", "libgl1-mesa-dri"]
                note = "Firmware, Vulkan and video acceleration for AMD Radeon graphics."
            elif vendor == "intel":
                packages = ["intel-media-va-driver-non-free", "i965-va-driver", "mesa-vulkan-drivers", "firmware-misc-nonfree"]
                note = "Video acceleration and Vulkan for Intel graphics."
            else:
                continue  # virtual GPUs (VirtualBox, QEMU) need nothing extra
        elif kind == "wifi":
            if vendor == "broadcom" and dev.get("deviceId") in BROADCOM_WL_IDS and arch == "amd64":
                packages = [headers, "broadcom-sta-dkms"]  # Broadcom's wl driver exists for Intel/AMD PCs only
                note = "This Broadcom Wi-Fi chip needs Broadcom's driver. Restart after installing."
            elif vendor == "intel":
                packages = ["firmware-iwlwifi"]
            elif vendor == "realtek":
                packages = ["firmware-realtek"]
            elif vendor in ("atheros", "qualcomm"):
                packages = ["firmware-atheros"]
            elif vendor == "broadcom":
                packages = ["firmware-brcm80211"]
            elif vendor == "mediatek":
                packages = ["firmware-mediatek"]
        elif kind == "bluetooth":
            packages = ["bluez-firmware"]
        elif kind == "audio" and vendor == "intel":
            packages = ["firmware-sof-signed"]
        elif kind in ("network", "audio") and dev.get("driver"):
            pass  # working with the kernel's driver
        else:
            continue
        out.append({
            "id": dev.get("slot", ""),
            "kind": kind,
            "title": title,
            "vendor": _short_vendor(dev),
            "driver": dev.get("driver"),
            "working": bool(dev.get("driver")),
            "packages": [p for p in packages if DRIVER_PACKAGE_RE.match(p)],
            "note": note,
            "restart": any(p in packages for p in ("broadcom-sta-dkms", nvidia_pkg or "nvidia-driver")),
        })
    extra = sorted({p for p in (isenkram or []) if p.startswith("firmware-") and DRIVER_PACKAGE_RE.match(p)})
    if extra:
        out.append({"id": "firmware", "kind": "firmware", "title": "Other device firmware", "vendor": "",
                    "driver": None, "working": True, "packages": extra, "restart": False,
                    "note": "Firmware Debian's hardware lookup suggests for this computer."})
    return out


def parse_input_devices(text: str) -> list[dict]:
    """Touch devices from /proc/bus/input/devices: {name, pen} for each touchscreen or pen digitizer."""
    out = []
    for block in text.split("\n\n"):
        name = re.search(r'^N: Name="(.*)"$', block, re.M)
        prop = re.search(r"^B: PROP=([0-9a-fA-F]+)$", block, re.M)
        if not name or not prop:
            continue
        try:
            direct = int(prop.group(1), 16) & INPUT_PROP_DIRECT
        except ValueError:
            continue
        if direct:
            label = name.group(1)
            out.append({"name": label, "pen": bool(re.search(r"pen|stylus|wacom", label, re.I))})
    return out


def _touch_title(what: str, name: str) -> str:
    """"ELAN9008:00 04F3:2C82" -> "Touchscreen (ELAN)"; "Wacom HID 5256 Finger" -> "Touchscreen (Wacom)"."""
    maker = re.match(r"[A-Za-z]+", name or "")
    return f"{what} ({maker.group(0)})" if maker and maker.group(0).lower() not in ("hid", "i2c", "usb") else what


def extra_devices(touch: list[dict], webcam: bool, pci: list[dict], sensors: list[str]) -> list[dict]:
    """Touchscreens, pens, webcams and Intel IPU6 cameras, beyond what lspci's classes cover."""
    out = []
    screens = [t for t in touch if not t["pen"]]
    pens = [t for t in touch if t["pen"]]
    if screens:
        packages = ["xserver-xorg-input-libinput", "onboard"]
        note = "Touch works right away. This adds the Onboard on-screen keyboard for typing without a keyboard"
        if "accel" in sensors:
            packages.append("iio-sensor-proxy")
            note += ", and the tilt sensor 2-in-1s use to turn the screen"
        out.append({"id": "touchscreen", "kind": "touch", "title": _touch_title("Touchscreen", screens[0]["name"]), "vendor": "",
                    "driver": "libinput", "working": True, "packages": packages, "restart": False,
                    "note": note + ". Desktop icons then open with one tap.", "touch": True})
    if pens:
        out.append({"id": "pen", "kind": "touch", "title": _touch_title("Pen", pens[0]["name"]), "vendor": "", "driver": "libinput",
                     "working": True, "packages": ["xserver-xorg-input-wacom"], "restart": False,
                     "note": "Pressure and buttons for the pen."})
    ipu = [d for d in pci if d.get("vendorId") == "8086" and d.get("deviceId") in IPU6_IDS]
    if ipu:
        out.append({"id": ipu[0].get("slot", "ipu6"), "kind": "camera", "title": "Intel IPU6 camera", "vendor": "Intel",
                    "driver": ipu[0].get("driver"), "working": bool(webcam),
                    "packages": ["firmware-misc-nonfree", "libcamera-ipa", "libcamera-tools", "gstreamer1.0-libcamera",
                                 "pipewire-libcamera"],
                    "restart": True,
                    "note": ("The built-in camera on many newer Intel laptops. This installs its firmware and libcamera; "
                             "restart afterwards. Linux support for these cameras is still new, so some models "
                             "don't show a picture yet.")})
    if webcam:
        out.append({"id": "webcam", "kind": "camera", "title": "Webcam", "vendor": "", "driver": "uvcvideo",
                    "working": True, "packages": ["v4l-utils", "gstreamer1.0-plugins-good"], "restart": False,
                    "note": "Works with the Camera app and video calls."})
    return out


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def iio_sensors(root: str = "/sys/bus/iio/devices") -> list[str]:
    """Kinds of motion sensors (accel, gyro, als...) the kernel found."""
    import os
    found = []
    try:
        names = os.listdir(root)
    except OSError:
        return []
    for entry in names:
        name = _read(f"{root}/{entry}/name").strip().lower()
        for kind in ("accel", "gyro", "als", "magn"):
            if kind in name and kind not in found:
                found.append(kind)
    return found


def parse_apt_policy(text: str) -> set[str]:
    """Packages `apt-cache policy` can install (they have a candidate version)."""
    out, current = set(), None
    for line in text.splitlines():
        if line and not line.startswith(" ") and line.endswith(":"):
            current = line[:-1]
        elif current and line.strip().startswith("Candidate:") and "(none)" not in line:
            out.add(current)
    return out


def _run(args: list[str], timeout: float = 20) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def installed_packages(names: list[str]) -> set[str]:
    if not names or not shutil.which("dpkg-query"):
        return set()
    out = _run(["dpkg-query", "-W", "-f", "${Package} ${db:Status-Abbrev}\n", *names])
    return {line.split()[0] for line in out.splitlines() if len(line.split()) > 1 and line.split()[1].startswith("ii")}


def secure_boot() -> bool | None:
    if not shutil.which("mokutil"):
        return None
    out = _run(["mokutil", "--sb-state"], 10).lower()
    return "enabled" in out if out else None


def scan() -> dict:
    """Hardware with recommended packages and whether they're already installed (no root needed)."""
    if not shutil.which("lspci"):
        return {"devices": [], "error": "lspci is missing (install pciutils)."}
    devices = parse_lspci(_run(["lspci", "-vmmnnk"]))
    nvidia = parse_nvidia_detect(_run(["nvidia-detect"], 30)) if shutil.which("nvidia-detect") and \
        any(d.get("vendorId") == "10de" and kind_of(d) == "graphics" for d in devices) else None
    isenkram = _run(["isenkram-lookup"], 60).split() if shutil.which("isenkram-lookup") else []
    from .power import has_camera
    items = recommend(devices, nvidia, isenkram)
    items += extra_devices(parse_input_devices(_read("/proc/bus/input/devices")), has_camera(), devices, iio_sensors())
    wanted = sorted({p for it in items for p in it["packages"]})
    if shutil.which("apt-cache") and wanted:  # only what this Debian can actually install
        known = parse_apt_policy(_run(["apt-cache", "policy", *wanted], 30))
        if known:
            for it in items:
                it["packages"] = [p for p in it["packages"] if p in known]
    have = installed_packages(sorted({p for it in items for p in it["packages"]}))
    for it in items:
        it["missing"] = [p for p in it["packages"] if p not in have]
    return {"devices": items, "secureBoot": secure_boot()}
