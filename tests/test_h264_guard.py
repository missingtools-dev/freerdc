import os
import stat
import tempfile
import unittest

from freerdc.freerdp import FreeRDPClient, build_args
from freerdc.freerdp.detect import probe
from freerdc.model import Profile


def fake_client(directory: str, name: str, version: str, help_text: str) -> str:
    """A shell script that answers --version and /help like a FreeRDP client."""
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write("#!/bin/sh\n"
                f'if [ "$1" = "--version" ]; then echo "This is FreeRDP version {version} (n/a)"; exit 0; fi\n'
                f"cat <<'EOF'\n{help_text}\nEOF\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class H264DetectionTest(unittest.TestCase):
    def test_probe_reads_support_from_the_clients_help(self):
        with tempfile.TemporaryDirectory() as d:
            v2_no = probe(fake_client(d, "xfreerdp-a", "2.6.1", "/gfx[:RFX]   RDP8 graphics pipeline"))
            v2_yes = probe(fake_client(d, "xfreerdp-b", "2.11.7", "/gfx-h264[:AVC420|AVC444]  H264"))
            v3_yes = probe(fake_client(d, "xfreerdp3", "3.15.0", "/gfx[: [[progressive|RFX|AVC420[:on|off]AVC444"))
            v3_no = probe(fake_client(d, "xfreerdp3-b", "3.1.0", "/gfx[:progressive]"))
        self.assertEqual([c.h264 for c in (v2_no, v2_yes, v3_yes, v3_no)], [False, True, True, False])

    def test_unreadable_help_assumes_support(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(probe(fake_client(d, "xfreerdp-c", "2.11.7", "")).h264)


class H264GuardTest(unittest.TestCase):
    P = Profile(host="h", username="u", gfx_h264="AVC444")

    def test_option_is_left_out_with_a_warning_for_a_client_without_h264(self):
        for major in (2, 3):
            client = FreeRDPClient("/x/xfreerdp", major, f"{major}.0.0", "x11", h264=False)
            r = build_args(self.P, client)
            self.assertFalse(any("h264" in a or a.startswith("/gfx") for a in r.args), major)
            self.assertEqual(len(r.warnings), 1)
            self.assertIn("H.264", r.warnings[0])

    def test_option_is_passed_when_supported(self):
        v2 = FreeRDPClient("/x/xfreerdp", 2, "2.11.7", "x11", h264=True)
        v3 = FreeRDPClient("/x/xfreerdp3", 3, "3.15.0", "x11", h264=True)
        self.assertIn("/gfx-h264:AVC444", build_args(self.P, v2).args)
        self.assertIn("/gfx:AVC444", build_args(self.P, v3).args)

    def test_no_warning_when_h264_was_not_requested(self):
        client = FreeRDPClient("/x/xfreerdp", 2, "2.6.1", "x11", h264=False)
        self.assertEqual(build_args(Profile(host="h", username="u"), client).warnings, [])


if __name__ == "__main__":
    unittest.main()
