import unittest

from freerdc.freerdp import FreeRDPClient, build_args
from freerdc.model import Profile

V2 = FreeRDPClient("/usr/bin/xfreerdp", 2, "2.11.7", "x11")
V3 = FreeRDPClient("/usr/bin/xfreerdp3", 3, "3.10.3", "x11")
SDL3 = FreeRDPClient("/usr/bin/sdl-freerdp3", 3, "3.10.3", "sdl")


def profile(**kw):
    return Profile(host="192.168.1.123", username="myuser", password="secret", **kw)


class ArgsTest(unittest.TestCase):
    def test_example_script_on_v2(self):
        r = build_args(profile(monitors=[1, 2], multimon=True, cert_mode="any"), V2)
        for expected in ("/v:192.168.1.123", "/u:myuser", "/monitors:1,2", "/multimon:force",
                         "/cert:ignore", "+clipboard", "+dynamic-resolution",
                         "+auto-reconnect", "/auto-reconnect-max-retries:5",
                         "/floatbar:sticky:on,default:visible,show:always"):
            self.assertIn(expected, r.args)

    def test_password_never_in_argv(self):
        r = build_args(profile(), V3)
        cmd = r.command(V3)
        self.assertEqual(cmd, [V3.path, "/args-from:stdin"])  # FreeRDP 3: no other args allowed
        self.assertFalse(any("secret" in x for x in cmd + r.args))
        payload = r.stdin_payload().splitlines()
        self.assertIn("/p:secret", payload)
        self.assertIn("/v:192.168.1.123", payload)
        self.assertNotIn("secret", " ".join(r.display_command(V3)))

    def test_v2_password_via_from_stdin(self):
        r = build_args(profile(domain="D"), V2)
        cmd = r.command(V2)
        self.assertEqual(cmd[-1], "/from-stdin:force")
        self.assertIn("/v:192.168.1.123", cmd)
        self.assertFalse(any("secret" in x for x in cmd))
        self.assertEqual(r.stdin_payload(), "secret\n")  # password only
        # without a user name FreeRDP 2 would also read user/domain from stdin: don't send it
        nouser = build_args(Profile(host="h", password="secret"), V2)
        self.assertEqual(nouser.secrets, [])
        self.assertEqual(nouser.command(V2), [V2.path, *nouser.args])
        self.assertEqual(len(nouser.warnings), 1)

    def test_no_password_uses_plain_argv(self):
        r = build_args(Profile(host="h"), V3)
        self.assertEqual(r.command(V3), [V3.path, *r.args])
        self.assertEqual(r.stdin_payload(), "")

    def test_clipboard_differs(self):
        self.assertIn("+clipboard", build_args(profile(), V2).args)
        self.assertIn("/clipboard", build_args(profile(), V3).args)
        self.assertIn("-clipboard", build_args(profile(clipboard=False), V3).args)

    def test_h264_differs(self):
        self.assertIn("/gfx-h264:AVC444", build_args(profile(gfx_h264="AVC444"), V2).args)
        self.assertIn("/gfx:AVC444", build_args(profile(gfx_h264="AVC444"), V3).args)

    def test_sdl_keeps_floatbar(self):
        r = build_args(profile(), SDL3)
        self.assertTrue(any(x.startswith("/floatbar") for x in r.args))
        self.assertEqual(r.warnings, [])

    def test_smart_sizing_excludes_dynamic_resolution(self):
        r = build_args(profile(smart_sizing=True, dynamic_resolution=True), V3)
        self.assertIn("/smart-sizing", r.args)
        self.assertNotIn("+dynamic-resolution", r.args)
        self.assertEqual(len(r.warnings), 1)

    def test_log_level_only_when_log_shown(self):
        self.assertNotIn("/log-level:DEBUG", build_args(profile(), V3).args)
        self.assertIn("/log-level:DEBUG", build_args(profile(show_log=True), V3).args)

    def test_cert_modes(self):
        fp = "ab" * 32
        colon = ":".join(["ab"] * 32)
        for client in (V2, V3):
            self.assertNotIn("/cert", " ".join(build_args(profile(), client).args))  # ask, none saved
            self.assertIn("/cert:ignore", build_args(profile(cert_mode="any"), client).args)
            self.assertIn("/cert:deny", build_args(profile(cert_mode="saved"), client).args)
            self.assertIn(f"/cert:deny,fingerprint:sha256:{colon}",
                          build_args(profile(cert_mode="saved", trusted_fingerprints=[fp]), client).args)
            self.assertIn(f"/cert:fingerprint:sha256:{colon}",
                          build_args(profile(trusted_fingerprints=[fp]), client).args)

    def test_smart_sizing_excludes_dynamic_resolution(self):
        r = build_args(profile(smart_sizing=True, dynamic_resolution=True), V3)
        self.assertIn("/smart-sizing", r.args)
        self.assertNotIn("+dynamic-resolution", r.args)
        self.assertEqual(len(r.warnings), 1)

    def test_log_level_only_when_log_shown(self):
        self.assertNotIn("/log-level:INFO", build_args(profile(), V3).args)
        self.assertIn("/log-level:INFO", build_args(profile(show_log=True), V3).args)




if __name__ == "__main__":
    unittest.main()
