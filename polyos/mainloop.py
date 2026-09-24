"""Calling into GTK/LightDM from the HTTP server's threads."""

from __future__ import annotations

import threading

from gi.repository import GLib


def on_main(fn, *args, timeout: float = 15.0):
    """Run fn on the GTK main thread and return its result (GTK, wnck and LightDM are not thread-safe)."""
    if threading.current_thread() is threading.main_thread():
        return fn(*args)
    done = threading.Event()
    box: dict = {}

    def runner():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # re-raised in the calling thread
            box["error"] = exc
        finally:
            done.set()
        return False

    GLib.idle_add(runner)
    if not done.wait(timeout):
        raise TimeoutError(f"{getattr(fn, '__name__', fn)} timed out on the main thread")
    if "error" in box:
        raise box["error"]
    return box.get("value")
