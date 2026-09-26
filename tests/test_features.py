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

    def test_installed_launcher(self):
        app = {"desktop": ["com.valvesoftware.Steam.desktop", "steam.desktop"]}
        with tempfile.TemporaryDirectory() as tmp:
            system, home = Path(tmp) / "apps", Path(tmp) / "home"
            system.mkdir()
            self.assertIsNone(store.installed_launcher(app, home, dirs=[str(system)]))
            (system / "steam.desktop").write_text("[Desktop Entry]\n")
            self.assertEqual(store.installed_launcher(app, home, dirs=[str(system)]), "steam.desktop")
            flatpak = home / ".local/share/flatpak/exports/share/applications"
            flatpak.mkdir(parents=True)
            (flatpak / "com.valvesoftware.Steam.desktop").write_text("[Desktop Entry]\n")
            self.assertEqual(store.installed_launcher(app, home, dirs=[str(system)]), "com.valvesoftware.Steam.desktop")

    def test_edition_apps_land_on_the_desktop(self):
        from polyos.core import EventBus, Settings
        from polyos.mock import MockBackend

        with tempfile.TemporaryDirectory() as tmp:
            backend = MockBackend(Settings(Path(tmp) / "settings.json"), EventBus(), home=Path(tmp) / "home")
            backend.update_settings({"desktopIcons": ["polyos-files.desktop"]})
            backend.add_desktop_shortcuts(["steam.desktop", None, "polyos-files.desktop", "steam.desktop"])
            self.assertEqual(backend.settings.get("desktopIcons"), ["polyos-files.desktop", "steam.desktop"])

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

        from polyos.core import Settings

        self.assertIn("Exec=polyos-ctl cloud xcloud", gaming.shortcut("xcloud"))  # shipped in the package
        self.assertEqual(gaming.cloud_id("polyos-cloud-luna.desktop"), "luna")
        self.assertIsNone(gaming.cloud_id("steam.desktop"))
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = Settings(home / "settings.json")
            self.assertEqual(gaming.enabled(settings, home), [])
            # a launcher left from before PolyOS shipped them still counts, and is tidied away
            gaming.apps_dir(home).mkdir(parents=True)
            (gaming.apps_dir(home) / "polyos-cloud-luna.desktop").write_text(gaming.shortcut("luna"))
            self.assertEqual(gaming.enabled(settings, home), ["luna"])
            self.assertEqual(gaming.set_enabled(settings, home, ["xcloud", "geforcenow"]), ["geforcenow", "xcloud"])
            self.assertFalse((gaming.apps_dir(home) / "polyos-cloud-luna.desktop").exists())
            self.assertEqual(settings.get("cloudGaming"), ["geforcenow", "xcloud"])
            self.assertEqual(gaming.set_enabled(settings, home, []), [])
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


class Arm64Tests(unittest.TestCase):
    def test_arch_names(self):
        from polyos.arch import debian_arch

        self.assertEqual(debian_arch("x86_64"), "amd64")
        self.assertEqual(debian_arch("aarch64"), "arm64")

    def test_drivers_use_this_computers_headers(self):
        nvidia = {"classId": "0300", "className": "VGA compatible controller", "vendorId": "10de", "vendor": "NVIDIA",
                  "device": "GA106", "deviceId": "2503"}
        wl = {"classId": "0280", "className": "Network controller", "vendorId": "14e4", "vendor": "Broadcom",
              "device": "BCM4360", "deviceId": "43a0"}
        arm = drivers.recommend([nvidia, wl], "nvidia-driver", [], arch="arm64")
        self.assertIn("linux-headers-arm64", arm[0]["packages"])
        self.assertTrue(all("broadcom-sta-dkms" not in d["packages"] for d in arm))  # Intel/AMD only
        self.assertTrue(drivers.DRIVER_PACKAGE_RE.match("linux-headers-arm64"))
        pc = drivers.recommend([nvidia, wl], "nvidia-driver", [], arch="amd64")
        self.assertIn("linux-headers-amd64", pc[0]["packages"])
        self.assertTrue(any("broadcom-sta-dkms" in d["packages"] for d in pc))

    def test_store_hides_intel_only_apps_on_arm(self):
        data = store.load()
        arm = store.for_arch(data, "arm64")
        ids = {a["id"] for a in arm["apps"]}
        self.assertNotIn("steam", ids)
        self.assertIn("vscode", ids)
        self.assertNotIn("steam", [aid for aid, _ in arm["packs"]["gaming"]["apps"]])
        self.assertIn("steam", {a["id"] for a in store.for_arch(data, "amd64")["apps"]})
        self.assertFalse(store.available({"arches": ["amd64"]}, "arm64"))
        self.assertTrue(store.available({}, "arm64"))


class AppsPageTests(unittest.TestCase):
    """Settings > Apps: startup apps and where installed apps came from."""

    def test_startup_entries(self):
        from polyos import startup

        with tempfile.TemporaryDirectory() as tmp:
            system, home = Path(tmp) / "xdg", Path(tmp) / "home"
            system.mkdir()
            (system / "nm-applet.desktop").write_text("[Desktop Entry]\nType=Application\nName=Network\nExec=nm-applet\n")
            (system / "gnome-only.desktop").write_text("[Desktop Entry]\nType=Application\nName=G\nOnlyShowIn=GNOME;\n")
            (system / "polyos-agent.desktop").write_text("[Desktop Entry]\nType=Application\nName=PolyOS\n")
            names = lambda: [(e["id"], e["enabled"]) for e in startup.entries(home, [system], ["PolyOS"])]  # noqa: E731
            self.assertEqual(names(), [("nm-applet.desktop", True), ("polyos-agent.desktop", True)])
            startup.set_enabled(home, "nm-applet.desktop", False, [system])
            self.assertIn("Hidden=true", (home / ".config/autostart/nm-applet.desktop").read_text())
            self.assertEqual(names()[0], ("nm-applet.desktop", False))
            startup.set_enabled(home, "nm-applet.desktop", True, [system])
            self.assertFalse((home / ".config/autostart/nm-applet.desktop").exists())  # the override is gone
            with self.assertRaises(ValueError):
                startup.set_enabled(home, "polyos-agent.desktop", False, [system])
            with self.assertRaises(ValueError):
                startup.set_enabled(home, "../../etc/passwd", False, [system])
            # your own: add, switch off (kept, Hidden), remove
            launcher = Path(tmp) / "code.desktop"
            launcher.write_text("[Desktop Entry]\nType=Application\nName=Code\nExec=code\n[Desktop Action new]\nName=New\n")
            startup.add(home, launcher)
            mine = next(e for e in startup.entries(home, [system], ["PolyOS"]) if e["id"] == "code.desktop")
            self.assertTrue(mine["own"] and mine["enabled"])
            startup.set_enabled(home, "code.desktop", False, [system])
            text = (home / ".config/autostart/code.desktop").read_text()
            self.assertIn("Hidden=true", text.split("[Desktop Action new]")[0])  # in the right section
            startup.remove(home, "code.desktop", [system])
            self.assertNotIn("code.desktop", [e["id"] for e in startup.entries(home, [system], ["PolyOS"])])

    def test_app_origins(self):
        self.assertEqual(store.parse_dpkg_search("firefox-esr: /usr/share/applications/firefox-esr.desktop\n"
                                                 "libreoffice-writer:amd64, x: /usr/share/applications/w.desktop\n"
                                                 "diversion by foo from: /x\n"),
                         {"/usr/share/applications/firefox-esr.desktop": "firefox-esr",
                          "/usr/share/applications/w.desktop": "libreoffice-writer"})
        with tempfile.TemporaryDirectory() as tmp:
            home, system, flat = Path(tmp) / "home", Path(tmp) / "apps", Path(tmp) / "flatpak/exports/share/applications"
            for d in (system, flat, home / ".local/share/applications"):
                d.mkdir(parents=True)
            (system / "vlc.desktop").write_text("x")
            (flat / "com.spotify.Client.desktop").write_text("x")
            (home / ".local/share/applications/my.desktop").write_text("x")
            dirs = [str(system), str(flat)]
            self.assertEqual(store.app_origin("vlc.desktop", home, dirs)["kind"], "debian")
            spotify = store.app_origin("com.spotify.Client.desktop", home, dirs)
            self.assertEqual((spotify["kind"], spotify["ref"], spotify["user"]), ("flatpak", "com.spotify.Client", False))
            self.assertEqual(store.app_origin("my.desktop", home, dirs)["kind"], "local")
            self.assertEqual(store.app_origin("../x.desktop", home, dirs)["kind"], "unknown")


class DisplaySoundTests(unittest.TestCase):
    """Settings > Display (xrandr modes) and Sound (pactl devices)."""

    XRANDR = """Screen 0: minimum 320 x 200, current 4480 x 1440, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 309mm x 174mm
   1920x1080     60.01*+  59.97    48.00
   1280x720      60.00
HDMI-1 connected 1080x1920+1920+0 left (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440    143.97 + 120.00    59.95
   1920x1080    144.00   120.00    60.00*
   1920x1080i    60.00
DP-1 disconnected (normal left inverted right x axis y axis)
VGA-1 connected (normal left inverted right x axis y axis)
   1024x768      60.00 +
"""

    def test_parse_xrandr(self):
        from polyos import display

        outs = {o["name"]: o for o in display.parse_xrandr(self.XRANDR)}
        self.assertEqual(sorted(outs), ["HDMI-1", "VGA-1", "eDP-1"])
        edp, hdmi, vga = outs["eDP-1"], outs["HDMI-1"], outs["VGA-1"]
        self.assertEqual((edp["primary"], edp["mode"], edp["rate"], edp["preferred"]), (True, "1920x1080", 60.01, "1920x1080"))
        self.assertEqual(edp["modes"][0]["rates"], [60.01, 59.97, 48.0])
        self.assertEqual((hdmi["mode"], hdmi["rate"], hdmi["rotation"], hdmi["preferred"]), ("1920x1080", 60.0, "left", "2560x1440"))
        self.assertEqual([m["size"] for m in hdmi["modes"]], ["2560x1440", "1920x1080"])  # the interlaced line merges in
        self.assertFalse(vga["active"])
        self.assertEqual(vga["preferred"], "1024x768")

    def test_validate_and_command(self):
        from polyos import display

        outs = display.parse_xrandr(self.XRANDR)
        display.validate(outs, "HDMI-1", "2560x1440", 143.97, "normal")
        for bad in (("DP-1", None, None, None), ("HDMI-1", "800x600", None, None),
                    ("HDMI-1", "2560x1440", 100.0, None), ("eDP-1", None, None, "sideways")):
            with self.assertRaises(ValueError):
                display.validate(outs, *bad)
        self.assertEqual(display.command("HDMI-1", "2560x1440", 143.97, "normal", True),
                         ["xrandr", "--output", "HDMI-1", "--mode", "2560x1440", "--rate", "143.97", "--rotate", "normal", "--primary"])

    def test_displays_setting(self):
        from polyos.core import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "s.json")
            settings.update({"displays": {"HDMI-1": {"size": "2560x1440", "rate": 143.97, "primary": True}}})
            self.assertEqual(settings.get("displays")["HDMI-1"]["rotation"], "normal")
            for bad in ({"HDMI-1": {"size": "big"}}, {"HDMI-1": {"rate": 5000}}, {"../x": {}}, {"A": {"rotation": "up"}}):
                with self.assertRaises(ApiError):
                    settings.update({"displays": bad})

    def test_pactl_devices(self):
        from polyos import system

        sinks = json.dumps([{"name": "alsa_output.analog", "description": "Speakers", "mute": False,
                             "volume": {"front-left": {"value_percent": "40%"}, "front-right": {"value_percent": "60%"}}}])
        sources = json.dumps([{"name": "alsa_output.analog.monitor", "description": "Monitor of Speakers", "monitor_of_sink": "alsa_output.analog"},
                              {"name": "alsa_input.mic", "description": "Microphone", "mute": True, "monitor_of_sink": "n/a",
                               "volume": {"mono": {"value_percent": "70%"}}}])
        self.assertEqual(system.parse_pactl_devices(sinks), [{"name": "alsa_output.analog", "description": "Speakers", "level": 50, "muted": False}])
        self.assertEqual(system.parse_pactl_devices(sources, inputs=True),
                         [{"name": "alsa_input.mic", "description": "Microphone", "level": 70, "muted": True}])
        self.assertEqual(system.parse_pactl_devices("not json"), [])

    def test_mock_routes(self):
        from polyos.core import EventBus, Settings
        from polyos.mock import MockBackend

        with tempfile.TemporaryDirectory() as tmp:
            backend = MockBackend(Settings(Path(tmp) / "settings.json"), EventBus(), home=Path(tmp) / "home")
            r = backend.displays_set("HDMI-1", "1920x1080", 144.0, "normal", True)
            hdmi = next(o for o in r["outputs"] if o["name"] == "HDMI-1")
            self.assertEqual((hdmi["mode"], hdmi["rate"], hdmi["primary"]), ("1920x1080", 144.0, True))
            self.assertTrue(backend.settings.get("displays")["HDMI-1"]["primary"])
            with self.assertRaises(ApiError):
                backend.displays_set("HDMI-1", "1920x1080", 75.0, None, False)
            d = backend.sound_set_device("output", "bluez_output.AC_12_2F.1")
            self.assertEqual(d["defaultOutput"], "bluez_output.AC_12_2F.1")
            with self.assertRaises(ApiError):
                backend.sound_set_device("input", "nope")


class HardwareCheckTests(unittest.TestCase):
    """The first-start hardware check and its full / balanced / light profiles."""

    def facts(self, **kw):
        base = {"cpu": "Intel Core i5", "cores": 8, "ram": 16 * 1024 ** 3, "renderer": "Mesa Intel Xe",
                "graphics": [{"name": "Intel Iris Xe [8086:9a49]", "driver": "i915"}], "arch": "x86_64"}
        return base | kw

    def test_parsers(self):
        from polyos import hwcheck

        self.assertEqual(hwcheck.parse_cpuinfo("processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz\n"),
                         "Intel Core i5-8250U CPU @ 1.60GHz")
        self.assertEqual(hwcheck.parse_cpuinfo("processor : 0\nBogoMIPS : 108\nModel : Raspberry Pi 4 Model B Rev 1.4\n"),
                         "Raspberry Pi 4 Model B Rev 1.4")
        self.assertEqual(hwcheck.parse_meminfo("MemTotal:        8041604 kB\nMemFree: 1 kB\n"), 8041604 * 1024)
        self.assertEqual(hwcheck.parse_renderer("direct rendering: Yes\nOpenGL renderer string: llvmpipe (LLVM 15.0.6, 256 bits)\n"),
                         "llvmpipe (LLVM 15.0.6, 256 bits)")

    def test_profiles(self):
        from polyos import hwcheck

        full = hwcheck.assess(self.facts())
        self.assertEqual((full["profile"], full["supported"]), ("full", True))
        self.assertEqual(full["items"][2]["value"], "Intel Iris Xe")  # PCI ids left out
        self.assertEqual(hwcheck.assess(self.facts(renderer="llvmpipe (LLVM 15)", graphics=[]))["profile"], "balanced")
        self.assertEqual(hwcheck.assess(self.facts(cores=2, ram=4 * 1024 ** 3))["profile"], "balanced")
        light = hwcheck.assess(self.facts(cores=2, ram=2 * 1024 ** 3))
        self.assertEqual(light["profile"], "light")
        self.assertEqual([i["status"] for i in light["items"]], ["ok", "low", "good"])
        self.assertFalse(hwcheck.assess(self.facts(ram=1024 ** 3))["supported"])

    def test_profile_settings_are_valid(self):
        from polyos import hwcheck
        from polyos.core import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "s.json")
            for name in hwcheck.PROFILES:
                self.assertEqual(settings.update(dict(hwcheck.PROFILE_SETTINGS[name]))["performanceProfile"], name)


class SpecialDriverTests(unittest.TestCase):
    """Touchscreens, pens and cameras in Driver Manager."""

    INPUT = """I: Bus=0018 Vendor=04f3 Product=2c82 Version=0100
N: Name="ELAN9008:00 04F3:2C82"
B: PROP=2
B: EV=1b

I: Bus=0018 Vendor=04f3 Product=2c82 Version=0100
N: Name="ELAN9008:00 04F3:2C82 Stylus"
B: PROP=2

I: Bus=0018 Vendor=06cb Product=cd8b Version=0100
N: Name="SYNA2BA6:00 06CB:CD8B Touchpad"
B: PROP=5

I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
B: PROP=0
"""

    def test_touch_and_cameras(self):
        touch = drivers.parse_input_devices(self.INPUT)
        self.assertEqual(touch, [{"name": "ELAN9008:00 04F3:2C82", "pen": False},
                                 {"name": "ELAN9008:00 04F3:2C82 Stylus", "pen": True}])  # not the touchpad
        ipu = [{"slot": "00:05.0", "classId": "0480", "vendorId": "8086", "deviceId": "a75d", "driver": "intel-ipu6"}]
        items = {it["id"]: it for it in drivers.extra_devices(touch, True, ipu, ["accel"])}
        self.assertEqual(set(items), {"touchscreen", "pen", "00:05.0", "webcam"})
        self.assertIn("iio-sensor-proxy", items["touchscreen"]["packages"])
        self.assertIn("pipewire-libcamera", items["00:05.0"]["packages"])
        for it in items.values():
            self.assertTrue(all(drivers.DRIVER_PACKAGE_RE.match(p) for p in it["packages"]), it)
        self.assertEqual(drivers.extra_devices([], False, [], []), [])

    def test_apt_policy(self):
        text = "onboard:\n  Installed: (none)\n  Candidate: 1.4.1-5\n  Version table:\nmissing-pkg:\n  Installed: (none)\n  Candidate: (none)\n"
        self.assertEqual(drivers.parse_apt_policy(text), {"onboard"})


class ComputerModelTests(unittest.TestCase):
    """The exact model and age from the firmware, and what they change."""

    def test_models(self):
        from polyos import hwcheck

        lenovo = hwcheck.describe_model({"sys_vendor": "LENOVO", "product_name": "82LN", "product_version": "IdeaPad 5 15ALC05",
                                         "bios_date": "03/14/2022", "chassis_type": "10"}, 2026)
        self.assertEqual((lenovo["maker"], lenovo["model"], lenovo["year"], lenovo["age"], lenovo["laptop"]),
                         ("Lenovo", "IdeaPad 5 15ALC05 (82LN)", 2022, 4, True))
        board = hwcheck.describe_model({"sys_vendor": "System manufacturer", "product_name": "System Product Name",
                                        "board_vendor": "ASUSTeK COMPUTER INC.", "board_name": "ROG STRIX B550-F GAMING",
                                        "chassis_type": "3"}, 2026)
        self.assertEqual((board["maker"], board["model"], board["laptop"], board["year"]), ("ASUS", "ROG STRIX B550-F GAMING", False, None))
        dell = hwcheck.describe_model({"sys_vendor": "Dell Inc.", "product_name": "Dell XPS 13 9310", "chassis_type": "31"}, 2026)
        self.assertEqual((dell["model"], dell["convertible"]), ("XPS 13 9310", True))

    def test_age_and_background(self):
        from polyos import hwcheck

        base = {"cpu": "i7", "cores": 8, "ram": 16 * 1024 ** 3, "renderer": "Mesa", "arch": "x86_64",
                "graphics": [{"name": "Intel", "driver": "i915"}]}
        new = hwcheck.assess(base | {"computer": {"maker": "Lenovo", "model": "IdeaPad", "year": 2023, "age": 3, "laptop": True}})
        self.assertEqual((new["profile"], new["background"], new["items"][0]["id"]), ("full", "normal", "model"))
        old = hwcheck.assess(base | {"computer": {"maker": "Dell", "model": "XPS", "year": 2016, "age": 10, "laptop": True}})
        self.assertEqual((old["profile"], old["background"]), ("balanced", "reduced"))
        small = hwcheck.assess(base | {"ram": 4 * 1024 ** 3})
        self.assertEqual(small["background"], "reduced")
