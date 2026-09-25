"""Settings > Display: each screen's resolution, refresh rate, orientation and which is the main one.

Reads `xrandr --query` and changes modes with `xrandr --output ...`. What you choose is kept in
the "displays" setting and applied again when PolyOS starts, so it survives restarts.
"""

from __future__ import annotations

import re

ROTATIONS = ("normal", "left", "right", "inverted")
_OUTPUT = re.compile(r"^(\S+) (connected|disconnected)( primary)?(?: (\d+)x(\d+)\+(\d+)\+(\d+))?(?: (normal|left|right|inverted))?")
_MODE = re.compile(r"^\s+(\d+)x(\d+)i?\s+(.*)$")
_RATE = re.compile(r"(\d+(?:\.\d+)?)(\*)?(\+)?")


def parse_xrandr(text: str) -> list[dict]:
    """Connected outputs: name, primary, current mode and rate, rotation, and every mode with its rates."""
    outputs: list[dict] = []
    current = None
    for line in text.splitlines():
        m = _OUTPUT.match(line)
        if m:
            current = None
            if m.group(2) != "connected":
                continue
            current = {"name": m.group(1), "primary": bool(m.group(3)), "active": m.group(4) is not None,
                       "rotation": m.group(8) or "normal", "mode": None, "rate": None, "preferred": None, "modes": []}
            outputs.append(current)
            continue
        if current is None:
            continue
        m = _MODE.match(line)
        if not m:
            continue
        size = f"{m.group(1)}x{m.group(2)}"
        rates = []
        for token in m.group(3).split():  # "60.01*+", "59.95", and sometimes a lone "+" or "*" after a rate
            r = _RATE.fullmatch(token)
            if r:
                rates.append(round(float(r.group(1)), 2))
            marks = token if token in ("+", "*", "*+") else (r.group(2) or "") + (r.group(3) or "") if r else ""
            if "*" in marks and rates:
                current["mode"], current["rate"] = size, rates[-1]
            if "+" in marks and not current["preferred"]:
                current["preferred"] = size
        known = next((md for md in current["modes"] if md["size"] == size), None)
        if known:
            known["rates"] = sorted(set(known["rates"] + rates), reverse=True)
        elif rates:
            current["modes"].append({"size": size, "rates": sorted(set(rates), reverse=True)})
    return outputs


def validate(outputs: list[dict], name: str, size: str | None, rate: float | None, rotation: str | None) -> None:
    """Refuse anything the screen doesn't offer (so a bad value can't blank it)."""
    out = next((o for o in outputs if o["name"] == name), None)
    if out is None:
        raise ValueError("That screen isn't connected.")
    if size is not None:
        mode = next((md for md in out["modes"] if md["size"] == size), None)
        if mode is None:
            raise ValueError(f"{name} can't show {size}.")
        if rate is not None and not any(abs(r - rate) < 0.05 for r in mode["rates"]):
            raise ValueError(f"{name} can't run {size} at {rate:g} Hz.")
    if rotation is not None and rotation not in ROTATIONS:
        raise ValueError("Choose an orientation.")


def command(name: str, size: str | None = None, rate: float | None = None, rotation: str | None = None,
            primary: bool = False) -> list[str]:
    args = ["xrandr", "--output", name]
    if size:
        args += ["--mode", size]
        if rate:
            args += ["--rate", f"{rate:g}"]
    if rotation:
        args += ["--rotate", rotation]
    if primary:
        args.append("--primary")
    return args
