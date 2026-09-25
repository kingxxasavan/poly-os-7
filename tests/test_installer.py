import unittest
from unittest import mock

from polyos import installer
from polyos.installer import GiB, MiB, InstallError

LSBLK = {"blockdevices": [
    {"name": "/dev/nvme0n1", "type": "disk", "size": 512110190592, "model": "Samsung SSD 970 EVO Plus 500GB", "tran": "nvme",
     "rm": False, "ro": False, "fstype": None, "label": None, "parttype": None, "partn": None, "mountpoints": [None],
     "pttype": "gpt", "children": [
         {"name": "/dev/nvme0n1p1", "type": "part", "size": 104857600, "fstype": "vfat", "label": "SYSTEM",
          "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "partn": 1, "mountpoints": [None]},
         {"name": "/dev/nvme0n1p3", "type": "part", "size": 510000000000, "fstype": "ntfs", "label": "Windows",
          "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "partn": 3, "mountpoints": [None]}]},
    {"name": "/dev/sdb", "type": "disk", "size": 32000000000, "model": "Ultra", "tran": "usb", "rm": True, "ro": False,
     "pttype": "dos", "mountpoints": [None], "children": [
         {"name": "/dev/sdb1", "type": "part", "size": 32000000000, "fstype": "iso9660", "partn": 1,
          "mountpoints": ["/run/live/medium"]}]},
    {"name": "/dev/zram0", "type": "disk", "size": 4000000000},
    {"name": "/dev/loop0", "type": "loop", "size": 1500000000},
]}

SFDISK = {"partitiontable": {"label": "gpt", "id": "X", "device": "/dev/sda", "unit": "sectors", "firstlba": 34,
                             "lastlba": 1000215182, "sectorsize": 512, "partitions": [
                                 {"node": "/dev/sda1", "start": 2048, "size": 1048576, "type": "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"},
                                 {"node": "/dev/sda2", "start": 1050624, "size": 400000000, "type": "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"}]}}


def disk(size=500 * GiB, table="gpt", parts=None):
    return {"path": "/dev/sda", "size": size, "model": "Disk", "transport": "sata", "removable": False,
            "readonly": False, "table": table, "mounts": [], "partitions": parts or []}


def part(path, number, size, fstype="ntfs", parttype=installer.MS_BASIC_GUID.lower()):
    return {"path": path, "number": number, "size": size, "fstype": fstype, "label": "", "parttype": parttype, "mounts": []}


class ParserTests(unittest.TestCase):
    def test_lsblk(self):
        disks = installer.parse_lsblk(LSBLK)
        self.assertEqual([d["path"] for d in disks], ["/dev/nvme0n1", "/dev/sdb"])  # no zram, no loop
        nvme = disks[0]
        self.assertEqual(nvme["table"], "gpt")
        self.assertFalse(nvme["removable"])
        self.assertEqual([p["number"] for p in nvme["partitions"]], [1, 3])
        self.assertEqual(disks[1]["partitions"][0]["mounts"], ["/run/live/medium"])
        self.assertTrue(disks[1]["removable"])

    def test_sfdisk_and_free_space(self):
        table = installer.parse_sfdisk(SFDISK)
        self.assertEqual(table["sector"], 512)
        self.assertEqual(table["partitions"][1]["number"], 2)
        regions = installer.free_regions(table, 1000215216 * 512)
        self.assertEqual(len(regions), 1)
        start = regions[0]["start"]
        self.assertEqual(start % 2048, 0)
        self.assertGreaterEqual(start, 1050624 + 400000000)
        self.assertLessEqual(start + regions[0]["size"], 1000215182 + 1)

    def test_os_prober(self):
        text = ("/dev/nvme0n1p1@/efi/Microsoft/Boot/bootmgfw.efi:Windows Boot Manager:Windows:efi\n"
                "/dev/sda2:Ubuntu 24.04 LTS (24.04):Ubuntu:linux\n")
        self.assertEqual(installer.parse_os_prober(text),
                         {"/dev/nvme0n1p1": "Windows", "/dev/sda2": "Ubuntu 24.04 LTS (24.04)"})

    def test_ntfsresize(self):
        ok = "ntfsresize v2022\nChecking filesystem consistency ...\nYou might resize at 131234525184 bytes or 131235 MB (freeing 378765 MB).\n"
        self.assertEqual(installer.parse_ntfsresize_info(ok), (131234525184, None))
        minimum, reason = installer.parse_ntfsresize_info("ERROR: The NTFS partition is hibernated. Windows must be resumed")
        self.assertIsNone(minimum)
        self.assertIn("Fast Startup", reason)

    def test_efibootmgr(self):
        text = ("BootCurrent: 0001\nBootOrder: 0003,0001,0000\n"
                "Boot0000* Windows Boot Manager\tHD(1,GPT,a,0x800,0x32000)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)\n"
                "Boot0003* debian\tHD(1,GPT,a,0x800,0x32000)/File(\\EFI\\debian\\shimx64.efi)\n")
        self.assertEqual(installer.efi_entries(text), {"0000": "Windows Boot Manager", "0003": "debian"})

    def test_partition_nodes(self):
        self.assertEqual(installer.partition_node("/dev/sda", 2), "/dev/sda2")
        self.assertEqual(installer.partition_node("/dev/nvme0n1", 2), "/dev/nvme0n1p2")
        self.assertEqual(installer.partition_node("/dev/mmcblk0", 1), "/dev/mmcblk0p1")


class PlanningTests(unittest.TestCase):
    def test_free_space_next_to_windows(self):
        d = disk(parts=[part("/dev/sda1", 1, 100 * MiB, "vfat", installer.ESP_GUID.lower()), part("/dev/sda2", 2, 200 * GiB)])
        d["free"] = [{"start": 420000000, "bytes": 290 * GiB}]
        for p in d["partitions"]:
            p["esp"] = installer.is_esp(p, "gpt")
        opt = installer.alongside_option(d, uefi=True)
        self.assertEqual(opt["kind"], "free")
        self.assertEqual(opt["extra"], 0)  # Windows' EFI partition is reused
        self.assertEqual(opt["maxBytes"], 290 * GiB)

    def test_shrink_windows(self):
        win = part("/dev/sda2", 2, 400 * GiB)
        win["resize"] = {"fs": "ntfs", "min": 120 * GiB, "used": 120 * GiB, "reason": None}
        d = disk(parts=[part("/dev/sda1", 1, 100 * MiB, "vfat", installer.ESP_GUID.lower()), win])
        d["free"] = []
        for p in d["partitions"]:
            p["esp"] = installer.is_esp(p, "gpt")
        opt = installer.alongside_option(d, uefi=True)
        self.assertEqual(opt["kind"], "shrink")
        self.assertEqual(opt["partition"], "/dev/sda2")
        self.assertLessEqual(opt["maxBytes"], 400 * GiB - 120 * GiB - installer.KEEP_FREE)
        self.assertGreaterEqual(opt["suggested"], installer.MIN_ROOT)

    def test_refusals(self):
        locked = part("/dev/sda2", 2, 400 * GiB, "BitLocker")
        locked["resize"] = {"fs": "bitlocker", "min": None, "reason": "This partition is encrypted with BitLocker."}
        d = disk(parts=[locked])
        d["free"] = []
        opt = installer.alongside_option(d, uefi=False)
        self.assertFalse(opt["possible"])
        self.assertIn("BitLocker", opt["reason"])
        legacy = disk(table="dos", parts=[part("/dev/sda1", 1, 400 * GiB, parttype="7")])
        legacy["free"] = [{"start": 2048, "bytes": 90 * GiB}]
        self.assertIn("legacy BIOS", installer.alongside_option(legacy, uefi=True)["reason"])
        full = disk(table="dos", parts=[part(f"/dev/sda{i}", i, 10 * GiB, parttype="83") for i in range(1, 5)])
        full["free"] = [{"start": 2048, "bytes": 90 * GiB}]
        self.assertIn("four primary", installer.alongside_option(full, uefi=False)["reason"])
        self.assertIn("empty", installer.alongside_option(disk(table=None), uefi=True)["reason"])

    def test_describe_marks_live_disk(self):
        disks = installer.parse_lsblk(LSBLK)
        live = installer.describe_disk(disks[1], None, {}, True, "/dev/sdb", {})
        self.assertTrue(live["isLive"])
        self.assertFalse(live["canErase"])
        windows = installer.describe_disk(disks[0], None, {"/dev/nvme0n1p1": "Windows 11"}, True, "/dev/sdb", {})
        self.assertEqual(windows["oses"], ["Windows 11"])

    def test_layouts(self):
        self.assertIn("label: gpt", installer.erase_script("gpt", uefi=True))
        self.assertIn(installer.ESP_GUID, installer.erase_script("gpt", uefi=True))
        self.assertIn("bootable", installer.erase_script("dos", uefi=False))
        self.assertIn(installer.BIOS_BOOT_GUID, installer.erase_script("gpt", uefi=False))
        parts = installer.alongside_layout(1000001, 40 * GiB, 512, "gpt", need_esp=True, need_bios=False)
        self.assertEqual([p["role"] for p in parts], ["esp", "root"])
        self.assertEqual(parts[0]["start"] % 2048, 0)
        self.assertEqual(parts[1]["start"], parts[0]["start"] + parts[0]["size"])
        self.assertEqual(parts[1]["size"] * 512, 40 * GiB)

    def test_fstab_and_swap(self):
        text = installer.fstab("r-uuid", "e-uuid", swapfile=True)
        self.assertIn("UUID=r-uuid  /  ext4", text)
        self.assertIn("/boot/efi", text)
        self.assertIn("/swapfile", text)
        self.assertNotIn("/boot/efi", installer.fstab("r", None, False))
        self.assertEqual(installer.swap_bytes(2 * GiB), 2 * GiB)
        self.assertEqual(installer.swap_bytes(32 * GiB), 4 * GiB)
        self.assertEqual(installer.swap_bytes(512 * MiB), 1 * GiB)


class PlanValidationTests(unittest.TestCase):
    def plan(self, **over):
        base = {"mode": "erase", "disk": "/dev/sda", "hostname": "savan-polyos", "timezone": "America/New_York",
                "user": {"fullName": "Savan Patel", "username": "savan", "password": "hunter2hunter2"},
                "appearance": {"theme": "light", "accent": "#9B7FE0"}}
        base.update(over)
        return base

    def test_valid(self):
        clean = installer.validate_plan(self.plan())
        self.assertEqual(clean["appearance"], {"theme": "light", "accent": "#9b7fe0"})
        self.assertEqual(clean["user"]["username"], "savan")

    def test_rejects(self):
        bad = [
            {"mode": "format-everything"},
            {"disk": "/dev/sda; rm -rf /"},
            {"user": {"fullName": "x", "username": "Root", "password": ""}},
            {"user": {"fullName": "x", "username": "root", "password": ""}},
            {"user": {"fullName": "a:b", "username": "ab", "password": ""}},
            {"hostname": "-bad-"},
            {"timezone": "../../etc/shadow"},
            {"mode": "alongside", "size": 1024},
        ]
        for over in bad:
            with self.subTest(over=over), self.assertRaises(InstallError):
                installer.validate_plan(self.plan(**over))

    def test_blank_password_allowed(self):
        clean = installer.validate_plan(self.plan(user={"fullName": "", "username": "andrew", "password": ""}))
        self.assertEqual(clean["user"]["fullName"], "andrew")


class DryRunTests(unittest.TestCase):
    def test_erase_dry_run_emits_commands_in_order(self):
        events = []
        plan = installer.validate_plan({"mode": "erase", "disk": "/dev/sda", "hostname": "t-polyos", "timezone": "UTC",
                                        "user": {"fullName": "T", "username": "tester", "password": "pw"},
                                        "appearance": {"theme": "dark", "accent": "#678fd9"}})
        with mock.patch.object(installer, "live_disk", return_value="/dev/sdb"), \
                mock.patch("pathlib.Path.is_dir", return_value=True):
            installer.Installer(plan, events.append, dry_run=True).run()
        commands = [e["log"].replace("\\", "/") for e in events if "log" in e]
        joined = "\n".join(commands)
        self.assertTrue(events[-1].get("done"))
        order = ["wipefs", "sfdisk --wipe", "mkfs.ext4", "mkfs.vfat", "chroot /mnt/polyos-target useradd",
                 "chpasswd", "grub-install --target=x86_64-efi", "update-grub", "umount"]
        positions = [next(i for i, c in enumerate(commands) if key in c) for key in order]
        self.assertEqual(positions, sorted(positions), joined)
        self.assertNotIn("pw", " ".join(c for c in commands if "chpasswd" in c))  # the password goes via stdin


if __name__ == "__main__":
    unittest.main()
