import os
import tempfile
import unittest

from freerdc import store
from freerdc.model import Profile


class DefaultsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self.tmp.cleanup()

    def test_factory_defaults(self):
        p, client = store.load_defaults()
        self.assertEqual((p.log_level, p.show_log, client), ("INFO", False, None))

    def test_round_trip_keeps_options_but_never_identity(self):
        p = Profile(host="srv", port=1234, username="me", domain="D", password="pw",
                    sound=True, fullscreen=True, extra_args=["/foo"],
                    trusted_fingerprints=["aa" * 32])
        store.save_defaults(p, "/usr/bin/xfreerdp3")
        got, client = store.load_defaults()
        self.assertEqual(client, "/usr/bin/xfreerdp3")
        self.assertTrue(got.sound and got.fullscreen)
        self.assertEqual(got.extra_args, ["/foo"])
        self.assertEqual((got.host, got.port, got.username, got.domain, got.password),
                         ("", 3389, "", "", ""))
        self.assertEqual(got.trusted_fingerprints, [])
        self.assertNotIn("pw", store._settings_file().read_text())

    def test_reset(self):
        store.save_defaults(Profile(sound=True), None)
        store.reset_defaults()
        self.assertFalse(store.load_defaults()[0].sound)


if __name__ == "__main__":
    unittest.main()
