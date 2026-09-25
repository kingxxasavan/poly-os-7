"""Driver Manager, PolyMarket, Task Manager parsers, appearance and the root helper's checks."""

import json
import tempfile
import unittest
from pathlib import Path

from polyos import admin, drivers, power, procs, recovery, store, theme, widgets
from polyos.core import ApiError

LSPCI = """Slot:	00:02.0
Class:	VGA compatible controller [0300]
Vendor:	Intel Corporation [8086]
Device:	UHD Graphics 620 [5917]
SVendor:	Lenovo [17aa]
SDevice:	ThinkPad T480 [225e]
Rev:	07
Driver:	i915
Module:	i915

Slot:	01:00.0
Class:	3D controller [0302]
Vendor:	NVIDIA Corporation [10de]
Device:	GP108M [GeForce MX150] [1d10]
Driver:	nouveau
Module:	nouveau

Slot:	03:00.0
Class:	Network controller [0280]
Vendor:	Broadcom Inc. and subsidiaries [14e4]
Device:	BCM4360 802.11ac Wireless Network Adapter [43a0]

Slot:	00:1f.3
Class:	Audio device [0403]
Vendor:	Intel Corporation [8086]
Device:	Sunrise Point-LP HD Audio [9d71]
Driver:	snd_hda_intel

Slot:	00:1f.6
Class:	Ethernet controller [0200]
Vendor:	Intel Corporation [8086]
Device:	Ethernet Connection (4) I219-V [15d8]
Driver:	e1000e
"""


class DriverTests(unittest.TestCase):
    def test_lspci(self):
        devices = drivers.parse_lspci(LSPCI)
        self.assertEqual(len(devices), 5)
        self.assertEqual(devices[1]["vendorId"], "10de")
        self.assertEqual(devices[1]["device"], "GP108M [GeForce MX150]")
        self.assertEqual(devices[1]["deviceId"], "1d10")
        self.assertNotIn("driver", devices[2])

    def test_recommendations(self):
        items = {i["id"]: i for i in drivers.recommend(drivers.parse_lspci(LSPCI), "nvidia-tesla-535-driver", ["firmware-realtek", "vim"])}
        self.assertIn("nvidia-tesla-535-driver", items["01:00.0"]["packages"])
        self.assertTrue(items["01:00.0"]["restart"])
        self.assertIn("intel-media-va-driver-non-free", items["00:02.0"]["packages"])
        self.assertEqual(items["03:00.0"]["packages"], ["linux-headers-amd64", "broadcom-sta-dkms"])
        self.assertFalse(items["03:00.0"]["working"])
        self.assertEqual(items["firmware"]["packages"], ["firmware-realtek"])  # "vim" is not a driver
        for item in items.values():
            for pkg in item["packages"]:
                self.assertRegex(pkg, drivers.DRIVER_PACKAGE_RE)

    def test_nvidia_detect(self):
        out = ("Detected NVIDIA GPUs:\n01:00.0 3D controller [0302]: NVIDIA Corporation GP108M [10de:1d10]\n\n"
               "Checking card:  NVIDIA Corporation GP108M\nYour card is supported by all driver versions.\n"
               "Your card is also supported by the Tesla 535 drivers series.\nIt is recommended to install the\n"
               "    nvidia-driver\npackage.\n")
        self.assertEqual(drivers.parse_nvidia_detect(out), "nvidia-driver")
        self.assertIsNone(drivers.parse_nvidia_detect("No NVIDIA GPU detected."))

    def test_allowlist(self):
        for ok in ("nvidia-driver", "firmware-amd-graphics", "broadcom-sta-dkms", "mesa-vulkan-drivers"):
            self.assertRegex(ok, drivers.DRIVER_PACKAGE_RE)
        for bad in ("bash", "openssh-server", "nvidia-driver; rm", "firmware-", "sudo"):
            self.assertNotRegex(bad, drivers.DRIVER_PACKAGE_RE)


class StoreTests(unittest.TestCase):
    def test_catalog_is_valid(self):
        data = store.load()
        apps = store.validate(data)
        self.assertGreater(len(apps), 25)
        self.assertTrue(apps["firefox"]["system"])
        self.assertEqual(apps["discord"]["source"], "flathub")
        for app in apps.values():
            self.assertTrue(app["icons"], app["id"])

    def test_catalog_rejects_bad_entries(self):
        good = {"categories": [["x", "X"]], "apps": [{"id": "a", "name": "A", "summary": "s", "description": "d",
                                                     "category": "x", "source": "debian", "packages": ["vlc"]}]}
        store.validate(good)
        for change in ({"packages": ["vlc; rm -rf /"]}, {"source": "curl"}, {"category": "nope"}, {"id": "../x"}):
            bad = json.loads(json.dumps(good))
            bad["apps"][0].update(change)
            with self.subTest(change=change), self.assertRaises(store.CatalogError):
                store.validate(bad)

    def test_apt_status(self):
        self.assertAlmostEqual(admin.parse_apt_status("dlstatus:1:50.0:Retrieving file 1 of 3")[0], 0.3)
        progress, text = admin.parse_apt_status("pmstatus:vlc:100:Installed vlc")
        self.assertAlmostEqual(progress, 0.98)
        self.assertEqual(text, "Installed vlc")
        self.assertIsNone(admin.parse_apt_status("Reading package lists..."))

    def test_admin_refuses_unknown_things(self):
        with self.assertRaises(admin.AdminError):
            admin.store_action("install", "not-an-app")
        with self.assertRaises(admin.AdminError):
            admin.store_action("remove", "firefox")  # part of PolyOS
        with self.assertRaises(admin.AdminError):
            admin.drivers_install(["openssh-server"])


class ProcsTests(unittest.TestCase):
    def test_stat_with_odd_names(self):
        stat = procs.parse_stat("4242 (Web Content (x)) S 1000 4242 4242 0 -1 4194560 100 0 0 0 250 50 0 0 20 0 31 0 900 0 0")
        self.assertEqual(stat["name"], "Web Content (x)")
        self.assertEqual(stat["ppid"], 1000)
        self.assertEqual(stat["ticks"], 300)
        self.assertEqual(stat["threads"], 31)

    def test_system_files(self):
        total, cores = procs.parse_cpu_times("cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 50 0 25 400 25 0 0 0 0 0\nintr 1\n")
        self.assertEqual(total, [150, 1000])
        self.assertEqual(len(cores), 1)
        mem = procs.parse_meminfo("MemTotal:       8000000 kB\nMemAvailable:   5000000 kB\nHugePages_Total:       0\n")
        self.assertEqual(mem["MemTotal"], 8000000 * 1024)
        net = ("Inter-|   Receive |  Transmit\n face |bytes    packets errs drop fifo frame compressed multicast|bytes\n"
               "    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n"
               "wlan0: 5000 10 0 0 0 0 0 0 700 5 0 0 0 0 0 0\n")
        self.assertEqual(procs.parse_net_dev(net), (5000, 700))
        disk = ("   8       0 sda 100 0 2000 0 50 0 4000 0 0 0 0\n   8       1 sda1 100 0 2000 0 50 0 4000 0 0 0 0\n"
                " 259       0 nvme0n1 10 0 30 0 5 0 60 0 0 0 0\n 259       1 nvme0n1p1 10 0 30 0 5 0 60 0 0 0 0\n"
                "   7       0 loop0 10 0 999 0 0 0 0 0 0 0 0\n")
        self.assertEqual(procs.parse_diskstats(disk), ((2000 + 30) * 512, (4000 + 60) * 512))


class ThemeTests(unittest.TestCase):
    def test_gtk_settings_keep_other_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gtk-3.0" / "settings.ini"
            path.parent.mkdir()
            path.write_text("[Settings]\ngtk-font-name=Inter 11\ngtk-application-prefer-dark-theme=1\n")
            theme.apply_gtk("light", Path(tmp))
            text = path.read_text()
            self.assertIn("gtk-font-name=Inter 11", text)
            self.assertIn("gtk-application-prefer-dark-theme=0", text)
            self.assertIn("gtk-icon-theme-name=Papirus", text)
            self.assertTrue((Path(tmp) / "gtk-4.0" / "settings.ini").is_file())

    def test_openbox_theme(self):
        rc = theme.openbox_rc("<theme>\n    <name>@THEME@</name>\n</theme><bottom>@PANEL_MARGIN@</bottom>", "light", 64)
        self.assertIn("<name>PolyOS-Light</name>", rc)
        self.assertIn("<bottom>64</bottom>", rc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rc.xml"
            path.write_text(rc)
            theme.switch_openbox(path, "dark")
            self.assertIn("<name>PolyOS</name>", path.read_text())


class RecoveryTests(unittest.TestCase):
    def test_keys(self):
        key = recovery.generate()
        self.assertRegex(key, r"^[0-9A-Z]{5}(-[0-9A-Z]{5}){4}$")
        self.assertTrue(recovery.looks_valid(key))
        record = recovery.make_record(key)
        self.assertNotIn(recovery.normalize(key), json.dumps(record))  # only the hash is stored
        self.assertTrue(recovery.check(record, key.lower().replace("-", " ")))  # typing style doesn't matter
        self.assertFalse(recovery.check(record, recovery.generate()))
        self.assertTrue(recovery.check(record, key.replace("0", "O").replace("1", "I")))  # look-alikes
        self.assertFalse(recovery.looks_valid("short"))

    def test_save_record_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            recovery.save_record("savan", recovery.make_record(recovery.generate()), root=Path(tmp))
            saved = Path(tmp) / "var/lib/polyos/recovery/savan"
            self.assertTrue(saved.is_file())


class WidgetsTests(unittest.TestCase):
    def test_rss(self):
        xml = (b'<?xml version="1.0"?><rss><channel><title>BBC</title>'
               b'<item><title>Headline one</title><link>https://www.bbc.co.uk/news/1</link><pubDate>Thu, 24 Sep 2026 20:00:00 GMT</pubDate></item>'
               b'<item><title>Bad link</title><link>javascript:alert(1)</link></item>'
               b'<item><title></title><link>https://x</link></item></channel></rss>')
        items = widgets.parse_rss(xml)
        self.assertEqual([i["title"] for i in items], ["Headline one"])

    def test_data_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = widgets.Widgets(Path(tmp) / "widgets.json", Path(tmp))
            self.assertIsNone(w.data()["weather"]["place"])
            w.update({"todo": [{"text": "Finish PolyOS", "done": False}, {"text": "   "}], "notes": "hi"})
            self.assertEqual(w.data()["todo"], [{"text": "Finish PolyOS", "done": False}])
            w.update({"weather": {"place": {"name": "Charlotte", "latitude": 35.2, "longitude": -80.8}, "units": "celsius"}})
            self.assertEqual(w.data()["weather"]["units"], "celsius")
            for bad in ({"weather": {"place": {"latitude": 999, "longitude": 0}}}, {"news": {"topic": "gossip"}},
                        {"clocks": ["../etc"]}, {"evil": 1}):
                with self.subTest(bad=bad), self.assertRaises(ApiError):
                    w.update(bad)


if __name__ == "__main__":
    unittest.main()


class PowerTests(unittest.TestCase):
    LIST = """  performance:
    CpuDriver:\tintel_pstate
    Degraded:   no

* balanced:
    CpuDriver:\tintel_pstate
    PlatformDriver:\tplatform_profile

  power-saver:
    CpuDriver:\tintel_pstate
"""

    def test_profiles(self):
        offered = power.parse_profiles(self.LIST)
        self.assertEqual(offered, ["performance", "balanced", "power-saver"])
        self.assertEqual(power.profile_for("saver", offered), "power-saver")
        self.assertEqual(power.profile_for("maximum", offered), "performance")
        self.assertEqual(power.profile_for("performance", ["balanced", "power-saver"]), "balanced")  # no performance here
        self.assertIsNone(power.profile_for("saver", []))

    def test_maximum_turns_timers_off(self):
        self.assertEqual(power.timers({"powerMode": "balanced", "screenOff": 10, "sleepAfter": 30}), (10, 30))
        self.assertEqual(power.timers({"powerMode": "maximum", "screenOff": 10, "sleepAfter": 30}), (0, 0))

    def test_camera_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(power.has_camera(root / "missing"))
            codec = root / "video0"
            codec.mkdir()
            (codec / "name").write_text("bcm2835-codec-decode\n")
            (codec / "index").write_text("0\n")
            self.assertFalse(power.has_camera(root))
            meta = root / "video2"
            meta.mkdir()
            (meta / "name").write_text("Integrated Camera: Integrated C\n")
            (meta / "index").write_text("1\n")
            self.assertFalse(power.has_camera(root))  # a metadata node alone isn't a camera
            cam = root / "video1"
            cam.mkdir()
            (cam / "name").write_text("Integrated Camera: Integrated C\n")
            (cam / "index").write_text("0\n")
            self.assertTrue(power.has_camera(root))

    def test_openbox_margin(self):
        rc = theme.openbox_rc("<margins><top>0</top><bottom>@PANEL_MARGIN@</bottom></margins>", "dark", 64)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rc.xml"
            path.write_text(rc)
            theme.set_openbox_margin(path, 0)
            self.assertIn("<bottom>0</bottom>", path.read_text())

    def test_panel_margin(self):
        from polyos.backend import DOCK_HEIGHT, PANEL_HEIGHT, dock_geometry, panel_margin

        self.assertEqual(panel_margin({"taskbarStyle": "floating", "taskbarAutoHide": False}), PANEL_HEIGHT)
        self.assertEqual(panel_margin({"taskbarStyle": "full", "taskbarAutoHide": False}), DOCK_HEIGHT)
        self.assertEqual(panel_margin({"taskbarStyle": "full", "taskbarAutoHide": True}), 0)
        self.assertEqual(dock_geometry({"taskbarStyle": "full"}, 1920, 1080), (0, 1080 - DOCK_HEIGHT, 1920, DOCK_HEIGHT))


class EditionTests(unittest.TestCase):
    def test_catalog_packs(self):
        data = store.load()
        apps = store.validate(data)
        for name in ("gaming", "developer"):
            pack = store.pack(data, name)
            self.assertTrue(all(aid in apps for aid, _ in pack["apps"]))
        gaming = {aid for aid, _ in store.pack(data, "gaming")["apps"]}
        self.assertTrue({"steam", "bottles", "heroic", "gamemode"} <= gaming)
        broken = json.loads(json.dumps(data))
        broken["packs"]["gaming"]["apps"].append(["not-an-app", True])
        with self.assertRaises(store.CatalogError):
            store.validate(broken)

    def test_admin_pack_only_installs_pack_apps(self):
        with self.assertRaises(admin.AdminError):
            admin.pack_install("gaming", ["vscode"])  # in the catalog, but not a gaming app
        with self.assertRaises(admin.AdminError):
            admin.pack_install("hacking", ["steam"])
        with self.assertRaises(admin.AdminError):
            admin.pack_install("gaming", [])

    def test_cloud_shortcuts(self):
        from polyos import gaming

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(gaming.set_shortcuts(home, ["geforcenow", "xcloud"]), ["geforcenow", "xcloud"])
            text = (gaming.apps_dir(home) / "polyos-cloud-xcloud.desktop").read_text()
            self.assertIn("Exec=polyos-ctl cloud xcloud", text)
            self.assertEqual(gaming.set_shortcuts(home, ["xcloud"]), ["xcloud"])
        have = lambda exe: exe == "chromium"  # noqa: E731
        self.assertEqual(gaming.browser_command("https://x", have, set())[:2], ["chromium", "--app=https://x"])
        self.assertEqual(gaming.browser_command("https://x", have, {"com.google.Chrome"})[:3],
                         ["flatpak", "run", "com.google.Chrome"])
        self.assertEqual(gaming.browser_command("https://x", lambda e: False, set()), ["xdg-open", "https://x"])
        with self.assertRaises(ValueError):
            gaming.open_cloud("../../bin/sh")

    def test_developer_overrides(self):
        from polyos import devmode

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config"
            self.assertIsNone(devmode.resolve(config, "css/polyos.css"))
            base = devmode.prepare(config)
            self.assertTrue((base / "css" / "user.css").is_file())
            self.assertEqual(devmode.resolve(config, "css/user.css"), (base / "css" / "user.css").resolve())
            (Path(tmp) / "secret.txt").write_text("x")
            self.assertIsNone(devmode.resolve(config, "../../secret.txt"))  # never outside the folder
            aside = devmode.reset(config)
            self.assertTrue(aside.name.startswith("ui-off-"))
            self.assertIsNone(devmode.resolve(config, "css/user.css"))


class SecurityTests(unittest.TestCase):
    def test_parsers(self):
        from polyos import installer, security

        self.assertTrue(security.firewall_enabled("# ufw\nENABLED=yes\nLOGLEVEL=low\n"))
        self.assertFalse(security.firewall_enabled("ENABLED=no\n"))
        self.assertTrue(security.updates_enabled(security.AUTO_UPGRADES_TEXT.format(on=1)))
        self.assertFalse(security.updates_enabled(security.AUTO_UPGRADES_TEXT.format(on=0)))
        self.assertIn("ENABLED=yes", installer.firewall_conf("ENABLED=no\nLOGLEVEL=low\n"))
        self.assertNotIn("ENABLED=no", installer.firewall_conf("ENABLED=no\n"))

    def test_unlock_throttle(self):
        from polyos import security
        from polyos.core import ApiError

        now = [0.0]
        t = security.Throttle(limit=3, wait=30, clock=lambda: now[0])
        for _ in range(2):
            t.check()
            t.failed()
        t.check()  # the third try is still allowed
        t.failed()
        with self.assertRaises(ApiError) as caught:
            t.check()
        self.assertEqual(caught.exception.status, 429)
        now[0] = 31
        t.check()
        t.failed()  # a fourth wrong password doubles the wait
        now[0] = 31 + 59
        with self.assertRaises(ApiError):
            t.check()
        t.succeeded()
        t.check()
