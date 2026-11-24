import os
import tempfile
import unittest

try:
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import PasswordDeleteError
except ImportError:  # pragma: no cover
    keyring = None

from freerdc import store
from freerdc.model import Profile

if keyring:
    class MemoryKeyring(KeyringBackend):
        priority = 1

        def __init__(self):
            self.data = {}
            self.fail = False

        def _check(self):
            if self.fail:
                raise keyring.errors.KeyringLocked("keyring is locked")

        def set_password(self, service, username, password):
            self._check(); self.data[(service, username)] = password

        def get_password(self, service, username):
            self._check(); return self.data.get((service, username))

        def delete_password(self, service, username):
            self._check()
            if (service, username) not in self.data:
                raise PasswordDeleteError("not found")
            del self.data[(service, username)]


@unittest.skipUnless(keyring, "keyring not installed")
class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        self.kr = MemoryKeyring()
        self._old_kr = keyring.get_keyring()
        keyring.set_keyring(self.kr)

    def tearDown(self):
        keyring.set_keyring(self._old_kr)
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self.tmp.cleanup()

    def profile(self, user="alice", pw="pw1"):
        return Profile(host="h", username=user, password=pw)

    def test_roundtrip_and_no_password_on_disk(self):
        store.save_profile("c", self.profile(), True)
        self.assertEqual(store.load_profile("c").password, "pw1")
        self.assertNotIn("pw1", (store.config_dir() / "c.json").read_text())

    def test_changing_username_keeps_password(self):
        store.save_profile("c", self.profile("alice"), True)
        store.save_profile("c", self.profile("bob", ""), True)  # remember ticked, box empty
        self.assertEqual(store.load_profile("c").password, "pw1")
        self.assertEqual(len(self.kr.data), 1)  # nothing orphaned

    def test_unticking_remember_removes_password(self):
        store.save_profile("c", self.profile(), True)
        store.save_profile("c", self.profile(), False)
        self.assertEqual(self.kr.data, {})
        self.assertEqual(store.load_profile("c").password, "")

    def test_names_with_spaces_and_punctuation_keep_their_password(self):
        store.save_profile("My Server (prod)", self.profile("alice", "pw-space"), True)
        self.assertIn("My Server (prod)", store.list_profiles())  # shown as typed, not as the file name
        self.assertEqual(store.load_profile("My Server (prod)").password, "pw-space")
        store.delete_profile("My Server (prod)")
        self.assertEqual(self.kr.data, {})
        self.assertNotIn("My Server (prod)", store.list_profiles())

    def test_legacy_entry_is_migrated(self):
        store.save_profile("c", self.profile("alice", ""), False)
        self.kr.data[(store.SERVICE, "c|alice")] = "old"
        self.assertEqual(store.load_profile("c").password, "old")
        self.assertEqual(self.kr.data, {(store.SERVICE, "c"): "old"})

    def test_delete_profile_removes_password(self):
        store.save_profile("c", self.profile(), True)
        store.delete_profile("c")
        self.assertEqual(self.kr.data, {})
        self.assertNotIn("c", store.list_profiles())

    def test_keyring_failure_is_reported_but_profile_is_saved(self):
        self.kr.fail = True
        with self.assertRaises(store.CredentialStoreError):
            store.save_profile("c", self.profile(), True)
        self.assertIn("c", store.list_profiles())
        with self.assertRaises(store.CredentialStoreError):
            store.load_profile("c")
        self.assertEqual(store.load_profile("c", with_password=False).host, "h")


@unittest.skipUnless(keyring, "keyring not installed")
class ServerPasswordTest(unittest.TestCase):
    """Passwords remembered per server (the recent-servers list), kept in the keyring."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        self.kr = MemoryKeyring()
        self._old_kr = keyring.get_keyring()
        keyring.set_keyring(self.kr)

    def tearDown(self):
        keyring.set_keyring(self._old_kr)
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self.tmp.cleanup()

    def settings_text(self):
        return (store.config_dir().parent / "settings.json").read_text()

    def test_remember_and_recall(self):
        store.record_recent_server("10.0.0.5", 3389, "alice")
        self.assertFalse(store.recent_servers()[0]["remember"])
        store.remember_server_password("10.0.0.5", 3389, "s3cret")
        self.assertTrue(store.recent_servers()[0]["remember"])
        self.assertEqual(store.server_password("10.0.0.5", 3389), "s3cret")
        self.assertNotIn("s3cret", self.settings_text())  # only a flag is stored on disk

    def test_connecting_again_keeps_the_flag(self):
        store.record_recent_server("h", 3389, "alice")
        store.remember_server_password("h", 3389, "pw")
        store.record_recent_server("H", 3389, "alice")  # same server, another connect
        self.assertTrue(store.recent_servers()[0]["remember"])

    def test_port_makes_a_different_server(self):
        store.record_recent_server("h", 3389, "u"); store.remember_server_password("h", 3389, "a")
        store.record_recent_server("h", 3390, "u"); store.remember_server_password("h", 3390, "b")
        self.assertEqual(store.server_password("h", 3389), "a")
        self.assertEqual(store.server_password("h", 3390), "b")

    def test_forget_removes_it(self):
        store.record_recent_server("h", 3389, "u"); store.remember_server_password("h", 3389, "pw")
        store.forget_server_password("h", 3389)
        self.assertIsNone(store.server_password("h", 3389))
        self.assertFalse(store.recent_servers()[0]["remember"])

    def test_forget_never_touches_the_keyring_when_nothing_was_remembered(self):
        store.record_recent_server("h", 3389, "u")
        self.kr.fail = True  # a broken or missing keyring must not matter here
        store.forget_server_password("h", 3389)

    def test_clearing_the_history_removes_the_passwords_too(self):
        store.record_recent_server("a", 3389, "u"); store.remember_server_password("a", 3389, "pw")
        store.record_recent_server("b", 3389, "u")
        store.clear_recent_servers()
        self.assertEqual(store.recent_servers(), [])
        self.assertEqual(self.kr.data, {})

    def test_find_saved_password_checks_the_server_entry_and_saved_connections(self):
        # saved only for the server (after a connect)
        store.record_recent_server("srv", 3389, "alice"); store.remember_server_password("srv", 3389, "pw-server")
        self.assertEqual(store.find_saved_password("srv", 3389, "alice"), "pw-server")
        self.assertEqual(store.find_saved_password("SRV", 3389, "ALICE"), "pw-server")  # case-insensitive
        # saved only under a named connection
        store.save_profile("Work", Profile(host="box", username="bob", password="pw-named"), True)
        self.assertEqual(store.find_saved_password("box", 3389, "bob"), "pw-named")

    def test_find_saved_password_never_crosses_users_or_ports(self):
        store.record_recent_server("srv", 3389, "alice"); store.remember_server_password("srv", 3389, "pw-server")
        store.save_profile("Work", Profile(host="box", username="bob", password="pw-named"), True)
        self.assertIsNone(store.find_saved_password("srv", 3389, "mallory"))   # other user
        self.assertIsNone(store.find_saved_password("srv", 3390, "alice"))     # other port
        self.assertIsNone(store.find_saved_password("box", 3389, "alice"))     # other user
        self.assertIsNone(store.find_saved_password("box", 3389, ""))          # no user to match a profile
        self.assertIsNone(store.find_saved_password("nowhere", 3389, "alice"))

    def test_find_saved_password_only_touches_the_keyring_for_real_candidates(self):
        store.record_recent_server("srv", 3389, "alice")  # nothing remembered
        self.kr.fail = True                                # a broken keyring must not matter
        self.assertIsNone(store.find_saved_password("srv", 3389, "alice"))

    def test_keyring_failure_is_reported(self):
        store.record_recent_server("h", 3389, "u")
        self.kr.fail = True
        with self.assertRaises(store.CredentialStoreError):
            store.remember_server_password("h", 3389, "pw")
        self.assertFalse(store.recent_servers()[0]["remember"])  # not marked if it wasn't stored


@unittest.skipUnless(keyring, "keyring not installed")
class TrustedCertificatesTest(unittest.TestCase):
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

    def test_trust_survives_and_is_per_server(self):
        store.trust_certificate("10.0.0.5", 3389, "aa" * 32)
        store.trust_certificate("10.0.0.5", 3390, "bb" * 32)
        self.assertEqual(store.trusted_certificates("10.0.0.5", 3389), ["aa" * 32])
        self.assertEqual(store.trusted_certificates("10.0.0.5", 3390), ["bb" * 32])
        self.assertEqual(store.trusted_certificates("other", 3389), [])

    def test_same_fingerprint_is_not_added_twice_and_host_case_is_ignored(self):
        store.trust_certificate("Srv", 3389, "aa" * 32)
        store.trust_certificate("srv", 3389, "aa" * 32)
        self.assertEqual(store.trusted_certificates("SRV", 3389), ["aa" * 32])

    def test_forget(self):
        store.trust_certificate("h", 3389, "aa" * 32)
        store.trust_certificate("h", 3389, "bb" * 32)
        store.forget_certificate("h", 3389, "aa" * 32)
        self.assertEqual(store.trusted_certificates("h", 3389), ["bb" * 32])
        store.forget_certificate("h", 3389, "bb" * 32)
        self.assertEqual(store.trusted_certificates("h", 3389), [])

    def test_shares_the_settings_file_with_the_history(self):
        store.record_recent_server("h", 3389, "u")
        store.trust_certificate("h", 3389, "aa" * 32)
        store.record_recent_server("h", 3389, "u2")  # must not wipe the trust list
        self.assertEqual(store.trusted_certificates("h", 3389), ["aa" * 32])
        store.clear_recent_servers()  # clearing the history is not revoking trust
        self.assertEqual(store.trusted_certificates("h", 3389), ["aa" * 32])


@unittest.skipUnless(keyring, "keyring not installed")
class RecentServersTest(unittest.TestCase):
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

    def test_newest_first_and_deduplicated(self):
        store.record_recent_server("a", 3389, "u1")
        store.record_recent_server("b", 3389, "u2")
        store.record_recent_server("A", 3389, "u3")  # same server, different case
        got = store.recent_servers()
        self.assertEqual([(e["host"], e["username"]) for e in got], [("A", "u3"), ("b", "u2")])

    def test_port_distinguishes_servers(self):
        store.record_recent_server("a", 3389, "u")
        store.record_recent_server("a", 3390, "u")
        self.assertEqual(len(store.recent_servers()), 2)
        self.assertEqual(store.server_label("a", 3390), "a:3390")
        self.assertEqual(store.server_label("a", 3389), "a")

    def test_capped(self):
        for i in range(store.MAX_RECENT + 5):
            store.record_recent_server(f"h{i}", 3389, "")
        got = store.recent_servers()
        self.assertEqual(len(got), store.MAX_RECENT)
        self.assertEqual(got[0]["host"], f"h{store.MAX_RECENT + 4}")

    def test_shares_settings_file_with_client_paths_and_clears(self):
        store.add_client_path(__file__)
        store.record_recent_server("a", 3389, "u")
        store.add_client_path(os.path.dirname(__file__))  # must not wipe the history
        self.assertEqual(len(store.recent_servers()), 1)
        store.clear_recent_servers()
        self.assertEqual(store.recent_servers(), [])
        self.assertIn(__file__, store.client_paths())

    def test_no_password_stored(self):
        store.record_recent_server("a", 3389, "u")
        self.assertNotIn("password", (store.config_dir().parent / "settings.json").read_text())


if __name__ == "__main__":
    unittest.main()

