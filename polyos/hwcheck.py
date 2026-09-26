"""The hardware check PolyOS runs when it first starts: is this computer a good fit, and if it's on
the slower side, which lighter setup suits it.

It looks at the processor (cores), the memory and the graphics (a real driver, or software
drawing such as llvmpipe in a virtual machine), and sorts the computer into one of three profiles:

  full      everything on: blur, glass, animations
  balanced  the same, minus blur and shadows when graphics are drawn in software
  light     for older or small computers: no blur, shadows or see-through glass, fewer widgets,
            shorter animations, and background extras off

Most computers from the last ten years land on "full". Nothing is ever refused: PolyOS runs on
anything that meets the minimum, just in a lighter form.
"""

from __future__ import annotations

import os
import re

GIB = 1024 ** 3
MIN_RAM = 1.5 * GIB           # below this PolyOS still starts, but it will feel slow
LIGHT_RAM = 3.2 * GIB         # "4 GB" computers report about 3.6-3.8 GiB; 2-3 GB ones go light
FULL_RAM = 5.5 * GIB          # 6-8 GB and up gets everything
SOFTWARE_RENDERERS = ("llvmpipe", "softpipe", "swrast", "software rasterizer")
PROFILES = ("full", "balanced", "light")

# What each profile changes in the settings (only what differs from a normal install).
PROFILE_SETTINGS = {
    "full": {"performanceProfile": "full", "effects": True, "lockNews": True},
    "balanced": {"performanceProfile": "balanced", "effects": False},
    "light": {"performanceProfile": "light", "effects": False, "glass": 100, "lockNews": False,
              "widgets": ["weather", "calendar", "system", "todo"]},
}
PROFILE_TEXT = {
    "full": "Everything on: blur, glass and animations.",
    "balanced": "Blur and shadows off, so windows move smoothly with this graphics.",
    "light": "A lighter PolyOS: no blur, shadows or see-through glass, quicker animations and fewer "
             "widgets and background extras, so more of this computer goes to your apps.",
}


def parse_cpuinfo(text: str) -> str:
    """The processor's name from /proc/cpuinfo (x86 "model name", ARM "Hardware"/"Model")."""
    for key in ("model name", "Model", "Hardware", "cpu model", "Processor"):
        m = re.search(rf"^{key}\s*:\s*(.+)$", text, re.M)
        if m and m.group(1).strip():
            return re.sub(r"\s+", " ", m.group(1)).replace("(R)", "").replace("(TM)", "").strip()
    return ""


def parse_meminfo(text: str) -> int:
    m = re.search(r"^MemTotal:\s*(\d+)\s*kB", text, re.M)
    return int(m.group(1)) * 1024 if m else 0


def parse_renderer(glxinfo: str) -> str:
    m = re.search(r"OpenGL renderer string:\s*(.+)", glxinfo)
    return m.group(1).strip() if m else ""


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def gather(graphics: list[dict], renderer: str = "") -> dict:
    """The facts, from /proc and what the backend found about graphics."""
    return {"cpu": parse_cpuinfo(_read("/proc/cpuinfo")), "cores": os.cpu_count() or 1,
            "ram": parse_meminfo(_read("/proc/meminfo")), "graphics": graphics, "renderer": renderer,
            "arch": os.uname().machine}


def _gib(n: int) -> str:
    gb = n / GIB
    return f"{round(gb)} GB" if gb >= 1.8 else f"{gb:.1f} GB"


def assess(facts: dict) -> dict:
    """Each part with a verdict (good / ok / low), the profile that fits, and a summary."""
    cores, ram, renderer = facts["cores"], facts["ram"], (facts.get("renderer") or "").lower()
    graphics = facts.get("graphics") or []
    software = any(s in renderer for s in SOFTWARE_RENDERERS)
    has_driver = any(g.get("driver") for g in graphics)

    cpu_status = "good" if cores >= 4 else "ok" if cores >= 2 else "low"
    ram_status = "good" if ram >= FULL_RAM else "ok" if ram >= LIGHT_RAM else "low"
    if software:
        gpu_status = "ok"
        gpu_note = "Drawn in software (a virtual machine or a missing driver): blur and shadows are turned off."
    elif graphics and not has_driver:
        gpu_status = "ok"
        gpu_note = "No driver in use yet: Driver Manager can install one."
    else:
        gpu_status = "good"
        gpu_note = "Hardware accelerated."
    gpu_name = graphics[0]["name"] if graphics else facts.get("renderer") or "Not detected"

    items = [
        {"id": "cpu", "label": "Processor", "value": f"{facts.get('cpu') or 'Processor'} · {cores} core{'s' if cores != 1 else ''}",
         "status": cpu_status, "note": {"good": "Plenty for PolyOS.", "ok": "Fine for everyday use.",
                                         "low": "A single core: PolyOS will run in its light mode."}[cpu_status]},
        {"id": "ram", "label": "Memory", "value": _gib(ram) if ram else "Unknown", "status": ram_status,
         "note": {"good": "Plenty for PolyOS and your apps.", "ok": "Enough for PolyOS and a few apps at a time.",
                  "low": "On the small side: the light mode leaves more of it to your apps."}[ram_status]},
        {"id": "gpu", "label": "Graphics", "value": re.sub(r"\s*\[[0-9a-f]{4}:[0-9a-f]{4}\]", "", gpu_name, flags=re.I),
         "status": gpu_status, "note": gpu_note},
    ]
    if cpu_status == "low" or ram_status == "low":
        profile = "light"
    elif software or cpu_status == "ok" and ram_status == "ok":
        profile = "balanced"
    else:
        profile = "full"
    supported = ram == 0 or ram >= MIN_RAM
    if profile == "full":
        summary = "This computer is a great fit for PolyOS."
    elif profile == "balanced":
        summary = "This computer runs PolyOS well. A few effects are turned off to keep it smooth."
    else:
        summary = "PolyOS runs in its light mode on a computer like this one."
    if not supported:
        summary = "This computer has less memory than PolyOS needs (2 GB). It will start, but expect it to be slow."
    return {"items": items, "profile": profile, "supported": supported, "summary": summary,
            "profileText": PROFILE_TEXT[profile], "arch": facts.get("arch", "")}
