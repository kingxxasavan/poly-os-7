import http.client
import json
import tempfile
import unittest
from pathlib import Path

from polyos import paths
from polyos.core import EventBus, Settings
from polyos.mock import MockBackend
from polyos.server import GREETER_API, Server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        backend = MockBackend(Settings(Path(cls.tmp.name) / "s.json"), EventBus(), home=Path(cls.tmp.name) / "home")
        cls.server = Server(backend, paths.UI_DIR, "secret-token", dev=False)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, token="secret-token", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.server.port}"}
        if token:
            headers["X-PolyOS-Token"] = token
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        return res.status, payload, res

    def test_requires_token(self):
        self.assertEqual(self.request("GET", "/api/state", token=None)[0], 401)
        self.assertEqual(self.request("GET", "/api/state", token="wrong")[0], 401)
        self.assertEqual(self.request("GET", f"/api/state?t=secret-token", token=None)[0], 200)

    def test_rejects_foreign_host(self):
        self.assertEqual(self.request("GET", "/api/state", host="evil.example:80")[0], 403)

    def test_state_shape(self):
        status, body, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        for key in ("version", "user", "settings", "apps", "windows", "system", "env"):
            self.assertIn(key, state)

    def test_static_files_and_traversal(self):
        status, body, res = self.request("GET", "/index.html", token=None)
        self.assertEqual(status, 200)
        self.assertIn("Content-Security-Policy", res.headers)
        self.assertNotIn(b"secret-token", body)  # the token is never served in production mode
        self.assertEqual(self.request("GET", "/../polyos/server.py", token=None)[0], 404)
        self.assertEqual(self.request("GET", "/%2e%2e/main.py", token=None)[0], 404)
        self.assertEqual(self.request("GET", "/dev.html", token=None)[0], 404)  # dev harness is dev-only

    def test_post_validation_and_actions(self):
        self.assertEqual(self.request("POST", "/api/launch", {})[0], 400)
        self.assertEqual(self.request("POST", "/api/power", {"action": "format-disk"})[0], 400)
        status, body, _ = self.request("POST", "/api/launch", {"id": "firefox-esr.desktop"})
        self.assertEqual(status, 200)
        windows = json.loads(self.request("GET", "/api/state")[1])["windows"]
        self.assertTrue(any(w["appId"] == "firefox-esr.desktop" for w in windows))
        status, body, _ = self.request("POST", "/api/settings", {"accent": "#22c55e"})
        self.assertEqual(json.loads(body)["accent"], "#22c55e")

    def test_run_command_and_new_popups(self):
        self.assertEqual(self.request("POST", "/api/run-command", {})[0], 400)
        status, body, _ = self.request("POST", "/api/run-command", {"command": "nosuchthing"})
        self.assertEqual(status, 500)
        self.assertIn("nosuchthing", json.loads(body)["error"])
        self.assertEqual(self.request("POST", "/api/run-command", {"command": "mousepad"})[0], 200)
        for view in ("start", "run", "power"):
            status, body, _ = self.request("POST", "/api/popup", {"view": view})
            self.assertEqual(status, 200, view)
            self.assertEqual(json.loads(body)["fullscreen"], view == "power")
        self.request("POST", "/api/popup", {"view": None})
        # the Windows key closes whatever menu is open, and opens the Home Menu otherwise
        self.request("POST", "/api/popup", {"view": "launcher"})
        self.assertIsNone(json.loads(self.request("POST", "/api/popup", {"view": "start", "toggle": True})[1] or b"null").get("view"))
        self.assertEqual(json.loads(self.request("POST", "/api/popup", {"view": "start", "toggle": True})[1])["view"], "start")
        self.request("POST", "/api/popup", {"view": None})

    def test_files_api(self):
        home = json.loads(self.request("GET", "/api/files/places")[1])["home"]
        listing = json.loads(self.request("GET", "/api/files/list?path=" + home.replace(" ", "%20"))[1])
        self.assertIn("Documents", [e["name"] for e in listing["entries"]])
        status, body, _ = self.request("POST", "/api/files/mkdir", {"parent": home, "name": "API test"})
        self.assertEqual(status, 200, body)
        created = json.loads(body)["path"]
        self.assertEqual(self.request("POST", "/api/files/trash", {"paths": [created]})[0], 200)
        trash = json.loads(self.request("GET", "/api/files/list?path=trash:///")[1])
        self.assertTrue(any(e["origin"] == created for e in trash["entries"]))
        self.assertEqual(self.request("POST", "/api/files/trash", {"paths": []})[0], 400)
        self.assertEqual(self.request("GET", "/files/raw?path=" + home, token=None)[0], 401)
        self.assertEqual(self.request("GET", "/files/raw?path=" + home + "/.bashrc")[0], 404)  # not an image

    def test_store_drivers_procs_and_admin(self):
        catalog = json.loads(self.request("GET", "/api/store")[1])
        self.assertTrue(any(a["id"] == "firefox" and a["installed"] for a in catalog["apps"]))
        self.assertEqual(self.request("POST", "/api/store/install", {"id": "nope"})[0], 404)
        self.assertEqual(self.request("POST", "/api/store/install", {"id": "vlc"})[0], 401)  # needs the password
        self.assertEqual(self.request("POST", "/api/admin/auth", {"password": "wrong"})[0], 403)
        self.assertEqual(self.request("POST", "/api/admin/auth", {"password": "polyos"})[0], 200)
        status, body, _ = self.request("POST", "/api/store/install", {"id": "vlc"})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["state"], "running")
        self.assertEqual(self.request("POST", "/api/store/install", {"id": "gimp"})[0], 409)  # one job at a time
        self.assertEqual(self.request("POST", "/api/store/remove", {"id": "firefox"})[0], 400)
        drivers = json.loads(self.request("GET", "/api/drivers")[1])
        self.assertTrue(any("nvidia-driver" in d["packages"] for d in drivers["devices"]))
        self.assertEqual(self.request("POST", "/api/drivers/install", {"packages": ["openssh-server"]})[0], 400)
        procs = json.loads(self.request("GET", "/api/procs")[1])
        self.assertIn("cpu", procs["perf"])
        self.assertEqual(self.request("POST", "/api/procs/end", {"pid": 1201})[0], 403)  # part of PolyOS
        self.assertEqual(self.request("GET", "/api/install/probe")[0], 409)  # not the live USB
        self.assertEqual(self.request("GET", "/icon/theme/vlc,video")[0], 200)

    def test_lock_screen(self):
        self.assertEqual(self.request("POST", "/api/power", {"action": "lock"})[0], 200)
        self.assertEqual(self.request("POST", "/api/lock/unlock", {"password": "nope"})[0], 403)
        self.assertEqual(self.request("POST", "/api/lock/unlock", {"password": "polyos"})[0], 200)
        self.assertEqual(self.request("POST", "/api/lock/recover", {"key": "bad", "password": "x"})[0], 403)
        self.assertEqual(self.request("POST", "/api/widgets/data", {"notes": "hello"})[0], 200)
        self.assertEqual(json.loads(self.request("GET", "/api/widgets/data")[1])["notes"], "hello")

    def test_icons_and_wallpaper(self):
        status, body, res = self.request("GET", "/icon/app/firefox-esr.desktop")
        self.assertEqual(status, 200)
        self.assertEqual(res.headers["Content-Type"], "image/svg+xml")
        status, _, res = self.request("GET", "/wallpaper/current")
        self.assertEqual(status, 200)
        self.assertTrue(res.headers["Content-Type"].startswith("image/"))
        self.assertEqual(self.request("GET", "/wallpaper/builtin/..%2F..%2Fmain.py")[0], 404)
        status, _, res = self.request("GET", "/wallpaper/lock")
        self.assertEqual(status, 200)
        self.assertTrue(res.headers["Content-Type"].startswith("image/"))

    def raw_post(self, path, data, ctype):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request("POST", path, body=data, headers={"Host": f"127.0.0.1:{self.server.port}",
                                                       "X-PolyOS-Token": "secret-token", "Content-Type": ctype})
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        return res.status, payload

    def test_camera_saves_to_pictures(self):
        info = json.loads(self.request("GET", "/api/camera")[1])
        self.assertTrue(info["camera"])
        jpeg = b"\xff\xd8\xff\xe0" + b"\0" * 200_000  # bigger than the JSON API's 64 KB limit
        status, body = self.raw_post("/api/camera/save?kind=photo", jpeg, "image/jpeg")
        self.assertEqual(status, 200, body)
        saved = Path(json.loads(body)["path"])
        self.assertEqual(saved.parent.name, "Camera")
        self.assertEqual(saved.read_bytes(), jpeg)
        self.assertEqual(self.raw_post("/api/camera/save?kind=photo", b"<html>", "image/jpeg")[0], 415)
        self.assertEqual(self.raw_post("/api/camera/save?kind=photo", jpeg, "text/html")[0], 415)
        self.assertEqual(self.raw_post("/api/camera/save?kind=exe", jpeg, "image/jpeg")[0], 400)
        status, body = self.raw_post("/api/camera/save?kind=video", b"\x1aE\xdf\xa3webm", "video/webm;codecs=vp8")
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["name"].endswith(".webm"))
        self.request("POST", "/api/settings", {"cameraAccess": False})
        try:
            self.assertEqual(self.raw_post("/api/camera/save?kind=photo", jpeg, "image/jpeg")[0], 403)
        finally:
            self.request("POST", "/api/settings", {"cameraAccess": True})

    def test_new_settings_and_power(self):
        ok = {"taskbarStyle": "full", "taskbarAlign": "left", "taskbarAutoHide": True, "powerMode": "maximum",
              "screenOff": 5, "sleepAfter": 0, "desktopIcons": ["firefox-esr.desktop"], "desktopOpen": "single"}
        status, body, _ = self.request("POST", "/api/settings", ok)
        self.assertEqual(status, 200, body)
        for bad in ({"taskbarStyle": "top"}, {"powerMode": "turbo"}, {"screenOff": 7}, {"screenOff": True},
                    {"desktopIcons": ["../x"]}):
            self.assertEqual(self.request("POST", "/api/settings", bad)[0], 400, bad)
        modes = json.loads(self.request("GET", "/api/power/modes")[1])
        self.assertEqual([m["id"] for m in modes["modes"]], ["saver", "balanced", "performance", "maximum"])
        perf = json.loads(self.request("GET", "/api/performance")[1])
        self.assertIn(perf["level"], ("optimal", "busy", "high"))
        # turning activity history off forgets it
        self.request("POST", "/api/launch", {"id": "firefox-esr.desktop"})
        state = json.loads(self.request("POST", "/api/settings", {"keepRecent": False})[1])
        self.assertEqual(state["recent"], [])
        self.request("POST", "/api/launch", {"id": "firefox-esr.desktop"})
        self.assertEqual(json.loads(self.request("GET", "/api/state")[1])["settings"]["recent"], [])
        self.request("POST", "/api/settings", {"keepRecent": True, "taskbarStyle": "floating", "taskbarAutoHide": False})


class GreeterServerTests(unittest.TestCase):
    """The login screen's server only answers what the login UI needs."""

    def test_restricted_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = MockBackend(Settings(Path(tmp) / "s.json"), EventBus(), home=Path(tmp) / "home")
            server = Server(backend, paths.UI_DIR, "tok", allow=GREETER_API)
            server.start()
            try:
                def get(path, method="GET", body=None):
                    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
                    data = json.dumps(body).encode() if body is not None else None
                    conn.request(method, path, body=data, headers={"Host": f"127.0.0.1:{server.port}", "X-PolyOS-Token": "tok",
                                                                   "Content-Type": "application/json"})
                    status = conn.getresponse().status
                    conn.close()
                    return status
                self.assertEqual(get("/api/state"), 200)
                self.assertEqual(get("/api/greeter/state"), 200)
                self.assertEqual(get("/api/performance"), 200)
                self.assertEqual(get("/wallpaper/lock"), 200)
                self.assertEqual(get("/api/camera"), 404)
                self.assertEqual(get("/api/files/places"), 404)
                self.assertEqual(get("/api/launch", "POST", {"id": "firefox-esr.desktop"}), 404)
                self.assertEqual(get("/api/run-command", "POST", {"command": "mousepad"}), 404)
                self.assertEqual(get("/api/greeter/login", "POST", {"user": "x", "password": "wrong"}), 403)
                self.assertEqual(get("/api/greeter/recover", "POST", {"user": "x", "key": "bad", "password": "p"}), 403)
                self.assertEqual(get("/api/lock/unlock", "POST", {"password": "polyos"}), 404)  # not on the login screen
            finally:
                server.stop()


class DebTests(unittest.TestCase):
    def test_packages_are_valid_ar_archives(self):
        import io
        import lzma  # noqa: F401 - tarfile needs it for .xz
        import tarfile

        import main

        with tempfile.TemporaryDirectory() as out:
            debs = [main.build_deb(name, Path(out)) for name in main.PACKAGES]
            for deb in debs:
                raw = deb.read_bytes()
                self.assertTrue(raw.startswith(b"!<arch>\n"))
                members, pos = {}, 8
                while pos < len(raw):
                    header = raw[pos:pos + 60]
                    name = header[:16].decode().strip()
                    size = int(header[48:58].decode())
                    members[name] = raw[pos + 60:pos + 60 + size]
                    pos += 60 + size + (size % 2)
                self.assertEqual(list(members), ["debian-binary", "control.tar.xz", "data.tar.xz"])
                self.assertEqual(members["debian-binary"], b"2.0\n")
                with tarfile.open(fileobj=io.BytesIO(members["control.tar.xz"])) as tar:
                    control = tar.extractfile("./control").read().decode()
                self.assertIn(f"Version: {main.VERSION}", control)
                with tarfile.open(fileobj=io.BytesIO(members["data.tar.xz"])) as tar:
                    names = tar.getnames()
                    if "polyos-shell" in deb.name:
                        self.assertIn("./usr/bin/polyos-session", names)
                        self.assertEqual(tar.getmember("./usr/bin/polyos-session").mode, 0o755)
                        self.assertIn("./usr/share/polyos/ui/index.html", names)
                        self.assertNotIn("./usr/share/polyos/ui/dev.html", names)
                        script = tar.extractfile("./usr/bin/polyos-shell").read()
                        self.assertNotIn(b"\r\n", script)
                        self.assertTrue(all(tar.getmember(n).uid == 0 for n in names))


if __name__ == "__main__":
    unittest.main()
