import json
import tempfile
import unittest
from pathlib import Path

from polyos.backend import REOPEN_GUARD
from polyos.core import ApiError, EventBus, Settings
from polyos.mock import MockBackend


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_and_persistence(self):
        s = Settings(self.path)
        self.assertEqual(s.get("scale"), "auto")
        s.update({"accent": "#AABBCC", "clock24h": True})
        again = Settings(self.path)
        self.assertEqual(again.get("accent"), "#aabbcc")
        self.assertTrue(again.get("clock24h"))

    def test_validation(self):
        s = Settings(self.path)
        for patch in ({"accent": "red"}, {"clock24h": "yes"}, {"nope": 1}, {"wallpaper": "../etc/passwd"},
                      {"wallpaper": "builtin:../x"}, {"pinned": ["bad id"]}, {"scale": "3"}):
            with self.assertRaises(ApiError, msg=patch):
                s.update(patch)
        self.assertEqual(s.update({"pinned": ["a.desktop", "a.desktop", "b.desktop"]})["pinned"],
                         ["a.desktop", "b.desktop"])

    def test_corrupt_file_is_ignored(self):
        self.path.write_text("{not json")
        self.assertEqual(Settings(self.path).get("accent"), "#678fd9")
        self.path.write_text(json.dumps({"accent": "nope", "clock24h": True}))
        s = Settings(self.path)
        self.assertEqual(s.get("accent"), "#678fd9")
        self.assertTrue(s.get("clock24h"))


class WallpaperTests(unittest.TestCase):
    def test_removed_builtin_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text(json.dumps({"wallpaper": "builtin:aurora.svg"}))  # shipped in 0.1, since removed
            backend = MockBackend(Settings(path), EventBus(), home=Path(tmp) / "home")
            self.assertEqual(backend.wallpaper_path().name, "polyos-dusk.jpg")

    def test_builtins_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = [w["id"] for w in MockBackend(Settings(Path(tmp) / "s.json"), EventBus(), home=Path(tmp) / "home").wallpapers()]
        self.assertIn("builtin:polyos-dusk.jpg", names)


class PopupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bus = EventBus()
        self.backend = MockBackend(Settings(Path(self.tmp.name) / "s.json"), self.bus, home=Path(self.tmp.name) / "home")

    def tearDown(self):
        self.tmp.cleanup()

    def test_toggle_and_switch(self):
        be = self.backend
        self.assertEqual(be.popup_request("start")["view"], "start")
        self.assertEqual(be.popup_request("quick")["view"], "quick")  # switching views
        self.assertIsNone(be.popup_request("quick"))  # same view again closes
        self.assertIsNone(be._popup)

    def test_blur_then_click_does_not_reopen(self):
        be = self.backend
        be.popup_request("start")
        be.popup_closed()  # focus left the popup because the Start button was clicked
        self.assertIsNone(be.popup_request("start"))
        be._last_closed = (be._last_closed[0], be._last_closed[1] - REOPEN_GUARD - 0.1)
        self.assertEqual(be.popup_request("start")["view"], "start")

    def test_rejects_unknown_views(self):
        with self.assertRaises(ApiError):
            self.backend.popup_request("nope")
        with self.assertRaises(ApiError):
            self.backend.popup_request("start", data="x")

    def test_events_are_published(self):
        q = self.bus.subscribe()
        self.backend.popup_request("calendar")
        event = json.loads(q.get_nowait())
        self.assertEqual(event["type"], "popup")
        self.assertEqual(event["popup"]["view"], "calendar")


if __name__ == "__main__":
    unittest.main()
