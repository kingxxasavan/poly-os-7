"""Developer mode: change PolyOS's own interface.

With developer mode on, any file in ~/.config/polyos/ui/ replaces the built-in file with the
same path (for example css/polyos.css or js/surfaces/panel.js), and css/user.css is added to
every PolyOS screen. ~/PolyOS-UI is a fresh copy of the built-in interface to read and copy
from. If a change breaks the desktop, Ctrl+Alt+T opens a terminal: `polyos-ctl dev off`.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

README = """PolyOS interface overrides (developer mode)
==========================================

Any file here replaces PolyOS's built-in file with the same path, on every PolyOS screen:

  css/user.css            added after PolyOS's styles: the easiest place to start
  css/polyos.css          the whole PolyOS stylesheet
  js/surfaces/panel.js    the taskbar (desktop.js, settings.js, lock.js ... the other screens)
  img/logo.svg            the pinwheel

~/PolyOS-UI has a copy of the built-in files: copy one here (same folder layout), edit it,
then use Settings > Developer > Reload the interface.

Broke something? Ctrl+Alt+T opens a terminal:  polyos-ctl dev off
(or delete this folder). Developer mode is off until you turn it on again.
"""

USER_CSS = """/* PolyOS user styles: added to every PolyOS screen while developer mode is on.
   Examples (remove the comment marks to try them):

:root { --accent: #ff7ab8; }                       -- a pink accent everywhere
html.composited .panel { border-radius: 12px; }    -- a squarer taskbar
.gr-clock { font-weight: 700; }                    -- a bolder lock screen clock
*/
"""


def override_dir(config_dir: Path) -> Path:
    return config_dir / "ui"


def resolve(config_dir: Path, rel: str) -> Path | None:
    """The override for a UI path, if there is one (never outside the override folder)."""
    base = override_dir(config_dir)
    if not rel or not base.is_dir():
        return None
    base = base.resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        return None
    return target


def prepare(config_dir: Path) -> Path:
    base = override_dir(config_dir)
    (base / "css").mkdir(parents=True, exist_ok=True)
    readme = base / "README.txt"
    if not readme.exists():
        readme.write_text(README, "utf-8")
    user_css = base / "css" / "user.css"
    if not user_css.exists():
        user_css.write_text(USER_CSS, "utf-8")
    return base


def copy_source(ui_dir: Path, home: Path) -> Path:
    """A fresh read-only reference copy of the built-in interface in ~/PolyOS-UI."""
    dest = home / "PolyOS-UI"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ui_dir, dest, ignore=shutil.ignore_patterns("dev.html", "dev.js", "dev.css", "fonts"))
    return dest


def reset(config_dir: Path) -> Path | None:
    """Put the overrides aside (renamed, not deleted) so PolyOS looks built-in again."""
    base = override_dir(config_dir)
    if not base.exists():
        return None
    aside = base.with_name(f"ui-off-{time.strftime('%Y%m%d-%H%M%S')}")
    base.rename(aside)
    return aside
