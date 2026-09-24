import unittest

from polyos import system

XRANDR = """Screen 0: minimum 8 x 8, current 2736 x 1824, maximum 32767 x 32767
eDP-1 connected primary 2736x1824+0+0 (normal left inverted right x axis y axis) 260mm x 173mm
   2736x1824     59.96*+
DP-1 disconnected (normal left inverted right x axis y axis)
"""


class ParserTests(unittest.TestCase):
    def test_split_terse_unescapes(self):
        self.assertEqual(system.split_terse(r"wlan0:wifi:connected:Cafe\:Guest"),
                         ["wlan0", "wifi", "connected", "Cafe:Guest"])
        self.assertEqual(system.split_terse("a::c"), ["a", "", "c"])
        self.assertEqual(system.split_terse(r"back\\slash:x"), ["back\\slash", "x"])

    def test_wpctl(self):
        self.assertEqual(system.parse_wpctl_volume("Volume: 0.40"), (40, False))
        self.assertEqual(system.parse_wpctl_volume("Volume: 0.73 [MUTED]"), (73, True))
        self.assertIsNone(system.parse_wpctl_volume("garbage"))

    def test_pactl(self):
        text = "Volume: front-left: 26214 /  40% / -23.88 dB,   front-right: 26214 /  40% / -23.88 dB"
        self.assertEqual(system.parse_pactl_volume(text), 40)

    def test_wifi_list_dedupes_and_sorts(self):
        out = "\n".join([
            " :Home:40:WPA2",
            " :Home:81:WPA2",
            "*:Office:55:WPA2 WPA3",
            " :Open Cafe:70:--",
            " ::90:WPA2",  # hidden network
        ])
        nets = system.parse_wifi_list(out, known={"Home"})
        self.assertEqual([n["ssid"] for n in nets], ["Office", "Home", "Open Cafe"])
        self.assertTrue(nets[0]["active"])
        self.assertEqual(nets[1]["signal"], 81)
        self.assertTrue(nets[1]["known"])
        self.assertFalse(nets[2]["secure"])

    def test_xrandr_dpi_and_scale(self):
        dpi = system.parse_xrandr_dpi(XRANDR)
        self.assertAlmostEqual(dpi, 267.3, delta=0.5)  # Surface Pro 4
        self.assertEqual(system.auto_scale(dpi), 2)
        self.assertEqual(system.auto_scale(96), 1)
        self.assertEqual(system.auto_scale(None), 1)
        self.assertIsNone(system.parse_xrandr_dpi("Virtual-1 connected primary 1280x800+0+0 0mm x 0mm"))


class RunCommandTests(unittest.TestCase):
    def test_rejects_empty_and_unknown_commands(self):
        with self.assertRaises(RuntimeError):
            system.run_command("   ")
        with self.assertRaises(RuntimeError) as ctx:
            system.run_command("definitely-not-a-real-program-8472 --flag")
        self.assertIn("definitely-not-a-real-program-8472", str(ctx.exception))
        with self.assertRaises(RuntimeError):
            system.run_command('echo "unterminated')


if __name__ == "__main__":
    unittest.main()
