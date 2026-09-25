"""Which processor family PolyOS runs on, in Debian's names: amd64 (Intel/AMD PCs) or arm64."""

from __future__ import annotations

import platform

ARCHES = ("amd64", "arm64")
_MACHINES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

# UEFI boot files per architecture: (grub-install target, shim, GRUB)
EFI = {
    "amd64": ("x86_64-efi", "shimx64.efi", "grubx64.efi"),
    "arm64": ("arm64-efi", "shimaa64.efi", "grubaa64.efi"),
}


def debian_arch(machine: str | None = None) -> str:
    m = (machine or platform.machine() or "").lower()
    return _MACHINES.get(m, m or "amd64")
