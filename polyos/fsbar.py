"""Full screen: only the app shows. The title bar and taskbar are gone; resting the pointer on the
top edge of the screen for a moment slides in a small bar with Minimize, Exit full screen and Close.

The bar is an override-redirect popup (it never takes focus from the app) and the top edge is
watched by polling the pointer, so no invisible window sits over the app catching its clicks.
Nothing here runs unless a full-screen app is in front.
"""

from __future__ import annotations

from gi.repository import Gdk, GLib, Gtk

POLL_MS = 150
DWELL_TICKS = 3   # ~0.45 s at the top edge before the bar appears (so games and quick flicks don't trigger it)
AWAY_TICKS = 5    # ~0.75 s away from the bar before it hides
HINT_MS = 2600    # shown briefly on entering full screen, as a reminder of how to leave

CSS = b"""
#polyos-fsbar { background: rgba(28, 28, 32, 0.96); border-radius: 14px; border: 1px solid rgba(255,255,255,0.12); }
#polyos-fsbar label { color: #f2f2f2; font-family: Poppins, Inter, sans-serif; font-weight: 600; font-size: 10.5pt; }
#polyos-fsbar label.hint { color: #b9b9c0; font-weight: 400; }
#polyos-fsbar button { background: rgba(255,255,255,0.08); border: none; border-radius: 10px; color: #f2f2f2;
                       box-shadow: none; padding: 4px 12px; min-height: 26px; }
#polyos-fsbar button:hover { background: rgba(255,255,255,0.16); }
#polyos-fsbar button.close:hover { background: #d9534f; }
"""


class FullscreenBar:
    def __init__(self, x_time):
        self._x_time = x_time
        self._win = None          # the Wnck window that's full screen
        self._timer = 0
        self._hint_timer = 0
        self._dwell = 0
        self._away = 0
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.bar = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.bar.set_name("polyos-fsbar")
        self.bar.set_wmclass("polyos-fsbar", "PolyOS")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_border_width(8)
        self.title = Gtk.Label(xalign=0)
        self.title.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.title.set_max_width_chars(40)
        self.hint = Gtk.Label(label="Move the pointer to the top to leave full screen")
        self.hint.get_style_context().add_class("hint")
        box.pack_start(self.title, True, True, 6)
        box.pack_start(self.hint, False, False, 6)
        for label, css, handler in (("Minimize", "min", self._minimize), ("Exit full screen", "exit", self._exit),
                                    ("Close", "close", self._close)):
            button = Gtk.Button(label=label)
            button.get_style_context().add_class(css)
            button.connect("clicked", lambda *_a, h=handler: h())
            box.pack_start(button, False, False, 0)
        self.bar.add(box)

    # ---- the shell tells us which window (if any) is full screen in front --------------------
    def track(self, win) -> None:
        if win is None:
            self._stop()
            return
        same = self._win is not None and self._win.get_xid() == win.get_xid()
        self._win = win
        if not self._timer:
            self._timer = GLib.timeout_add(POLL_MS, self._poll)
        if not same:
            self._cancel_hint()
            self._show(hint=True)
            self._hint_timer = GLib.timeout_add(HINT_MS, self._hint_done)

    def _stop(self) -> None:
        self._win = None
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self._cancel_hint()
        self.bar.hide()

    def _cancel_hint(self) -> None:
        if self._hint_timer:
            GLib.source_remove(self._hint_timer)
            self._hint_timer = 0

    def _hint_done(self):
        self._hint_timer = 0
        if not self._pointer_on_bar():
            self.bar.hide()
        return False

    # ---- showing and placing -----------------------------------------------------------------
    def _geometry(self):
        x, y, w, _h = self._win.get_geometry()
        return x, y, w

    def _show(self, hint: bool = False) -> None:
        if self._win is None:
            return
        self.title.set_text(self._win.get_name() or "")
        self.hint.set_visible(hint)
        self.bar.show_all()
        self.hint.set_visible(hint)
        width, _ = self.bar.get_preferred_width()
        x, y, w = self._geometry()
        self.bar.move(x + max(0, (w - width) // 2), y + 10)
        gdk = self.bar.get_window()
        if gdk is not None:
            gdk.raise_()  # above the full-screen app, which the window manager keeps on top

    def _pointer(self):
        display = Gdk.Display.get_default()
        _screen, px, py = display.get_default_seat().get_pointer().get_position()
        return px, py

    def _pointer_on_bar(self) -> bool:
        if not self.bar.get_visible():
            return False
        px, py = self._pointer()
        bx, by = self.bar.get_position()
        bw, bh = self.bar.get_size()
        return bx - 40 <= px <= bx + bw + 40 and py <= by + bh + 40

    def _poll(self):
        if self._win is None:
            self._timer = 0
            return False
        try:
            px, py = self._pointer()
            x, y, w = self._geometry()
        except Exception:  # noqa: BLE001 - the window went away between polls
            return True
        at_edge = x <= px < x + w and py <= y + 1
        if self.bar.get_visible():
            if self._hint_timer:
                return True
            self._away = 0 if self._pointer_on_bar() else self._away + 1
            if self._away >= AWAY_TICKS:
                self.bar.hide()
                self._away = 0
        else:
            self._dwell = self._dwell + 1 if at_edge else 0
            if self._dwell >= DWELL_TICKS:
                self._dwell = 0
                self._show()
        return True

    # ---- the buttons ----------------------------------------------------------------------
    def _minimize(self) -> None:
        if self._win is not None:
            self._win.minimize()
        self.bar.hide()

    def _exit(self) -> None:
        if self._win is not None:
            self._win.set_fullscreen(False)
        self.bar.hide()

    def _close(self) -> None:
        if self._win is not None:
            self._win.close(self._x_time())
        self.bar.hide()
