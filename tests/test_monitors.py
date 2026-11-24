import unittest

from freerdc.freerdp import FreeRDPClient
from freerdc.freerdp.monitors import monitor_list_command, parse_monitor_list

V2 = FreeRDPClient("/x/xfreerdp", 2, "2.11.7", "x11")
V3 = FreeRDPClient("/x/xfreerdp3", 3, "3.15.0", "x11")

# real output captured from the clients on the test machine
X11 = "     * [0] 1920x1080\t+0+0\n"
SDL = "listing 1 monitors:\n     * [1] [Virtual-1] 1920x1080\t+0+0\n"
TWO = "     * [0] 1920x1080\t+0+0\n       [1] 2560x1440\t-2560+120\n"


class MonitorsTest(unittest.TestCase):
    def test_option_spelling_per_version(self):
        self.assertEqual(monitor_list_command(V2)[1:], ["/monitor-list"])
        self.assertEqual(monitor_list_command(V3)[1:], ["/list:monitor"])  # singular!

    def test_x11_and_freerdp2_output(self):
        (m,) = parse_monitor_list(X11)
        self.assertEqual((m.id, m.width, m.height, m.x, m.y, m.primary, m.name), (0, 1920, 1080, 0, 0, True, ""))
        self.assertEqual(m.describe(), "Monitor 0: 1920x1080 at +0+0  (primary)")

    def test_sdl_output_is_one_based_and_named(self):
        (m,) = parse_monitor_list(SDL)
        self.assertEqual((m.id, m.name), (1, "Virtual-1"))
        self.assertIn("Monitor 1 [Virtual-1]", m.describe())

    def test_several_monitors_with_negative_offsets(self):
        a, b = parse_monitor_list(TWO)
        self.assertTrue(a.primary)
        self.assertFalse(b.primary)
        self.assertEqual((b.id, b.width, b.height, b.x, b.y), (1, 2560, 1440, -2560, 120))
        self.assertEqual(b.describe(), "Monitor 1: 2560x1440 at -2560+120")

    def test_usage_text_or_errors_yield_nothing(self):
        self.assertEqual(parse_monitor_list("Usage: xfreerdp3 [file] [options]\n  /a: <addin>\n"), [])
        self.assertEqual(parse_monitor_list(""), [])

    def test_log_noise_is_dropped_from_the_details_only_when_monitors_were_found(self):
        from unittest import mock
        import subprocess
        noisy = ("     * [0] 1920x1080\t+0+0\n"
                 "[19:13:26:955] [10523:0000291b] [WARN][com.freerdp.client] - client has been deprecated\n")
        fake = subprocess.CompletedProcess([], 0, stdout=noisy, stderr="")
        with mock.patch("freerdc.freerdp.monitors.subprocess.run", return_value=fake):
            from freerdc.freerdp.monitors import detect_monitors
            monitors, raw = detect_monitors(V3)
        self.assertEqual(len(monitors), 1)
        self.assertEqual(raw, "* [0] 1920x1080\t+0+0")
        failure = subprocess.CompletedProcess([], 24, stdout="", stderr="[19:13:26:955] [1:2] [ERROR] Invalid sigil\nUsage: x\n")
        with mock.patch("freerdc.freerdp.monitors.subprocess.run", return_value=failure):
            monitors, raw = detect_monitors(V3)
        self.assertEqual(monitors, [])
        self.assertIn("Invalid sigil", raw)  # kept: it explains the failure


if __name__ == "__main__":
    unittest.main()
