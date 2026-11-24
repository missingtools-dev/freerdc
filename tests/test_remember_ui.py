import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import keyring
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # pragma: no cover
    keyring = None

from test_store import MemoryKeyring  # noqa: E402  (the fake in-memory keyring)


@unittest.skipUnless(keyring, "keyring/PySide6 not installed")
class RememberCredentialsUiTest(unittest.TestCase):
    """Allow me to save credentials -> connect -> pick the server again -> password is back."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        self.kr = MemoryKeyring()
        self._old_kr = keyring.get_keyring()
        keyring.set_keyring(self.kr)
        from freerdc.ui.main_window import MainWindow
        self.warnings = []
        self._orig_warning = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda parent, title, text, *a: self.warnings.append(title) or 0)
        self.w = MainWindow()
        self.w.hide_on_connect.setChecked(False)
        self.w.remember.setEnabled(True)  # the fake keyring counts as available
        self.w.runner.start = lambda client, built: None  # never launch FreeRDP
        from freerdc.freerdp import FreeRDPClient
        self.w._client = lambda: FreeRDPClient("/usr/bin/xfreerdp3", 3, "3.15.0", "x11")
        import freerdc.ui.main_window as mw
        mw.build_args = lambda p, c: type("B", (), {"display_command": lambda s, c: [], "warnings": []})()
        self.w._ask_credentials = lambda target, user: self.fail("must not prompt")

    def tearDown(self):
        QMessageBox.warning = self._orig_warning
        keyring.set_keyring(self._old_kr)
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self.w.close()
        self.tmp.cleanup()

    def connect_to(self, host, user, password, remember):
        w = self.w
        w.host.setText(host); w.port.setValue(3389); w.username.setText(user)
        w.password.setText(password); w.remember.setChecked(remember)
        w._connect()
        w._on_connected()  # the session came up
        w.runner.running = lambda: False
        w.connect_btn.setText("Connect")

    def pick(self, label):
        w = self.w
        index = [w.host.itemText(i) for i in range(w.host.count())].index(label)
        w.host.setCurrentIndex(index)
        w._recent_picked(index)

    def test_saved_password_comes_back_when_the_server_is_picked_again(self):
        self.connect_to("192.0.2.10", "someuser", "example-password", remember=True)
        self.connect_to("other-server", "bob", "pw2", remember=False)
        w = self.w
        w.password.clear(); w.remember.setChecked(False)
        self.pick("192.0.2.10")
        self.assertEqual((w.host.text(), w.username.text(), w.password.text()), ("192.0.2.10", "someuser", "example-password"))
        self.assertTrue(w.remember.isChecked())

    def test_a_server_without_a_saved_password_clears_the_field(self):
        self.connect_to("192.0.2.10", "someuser", "example-password", remember=True)
        self.connect_to("other-server", "bob", "pw2", remember=False)
        self.pick("other-server")
        self.assertEqual(self.w.password.text(), "")
        self.assertFalse(self.w.remember.isChecked())

    def test_nothing_is_stored_without_the_checkbox_or_before_a_successful_logon(self):
        w = self.w
        w.host.setText("h"); w.username.setText("u"); w.password.setText("mistyped"); w.remember.setChecked(True)
        w._connect()  # attempt started but the logon never succeeded
        self.assertEqual(self.kr.data, {})
        self.connect_to("h2", "u", "pw", remember=False)
        self.assertEqual(self.kr.data, {})

    def test_unticking_the_box_forgets_the_saved_password(self):
        self.connect_to("192.0.2.10", "someuser", "example-password", remember=True)
        self.assertEqual(len(self.kr.data), 1)
        self.connect_to("192.0.2.10", "someuser", "example-password", remember=False)
        self.assertEqual(self.kr.data, {})

    def test_typed_server_uses_the_saved_password_without_asking(self):
        self.connect_to("192.0.2.10", "someuser", "example-password", remember=True)
        w = self.w
        w.runner.running = lambda: False
        w.password.clear(); w.host.setText("192.0.2.10"); w.username.setText("someuser")
        captured = []
        w.runner.start = lambda client, built: captured.append(1)
        w._connect()  # _ask_credentials would fail the test if it were called
        self.assertEqual(captured, [1])
        self.assertEqual(w.password.text(), "example-password")

    def test_named_connection_finds_the_password_saved_for_the_server(self):
        from freerdc import store
        from freerdc.model import Profile
        self.connect_to("192.0.2.10", "someuser", "example-password", remember=True)   # saved for the server
        store.save_profile("Test box", Profile(host="192.0.2.10", username="someuser"), False)  # no password of its own
        w = self.w
        w.host.setText("elsewhere"); w.username.setText("x"); w.password.clear(); w.remember.setChecked(False)
        w._refresh_trusted(); w._refresh_profiles()
        w.saved.setCurrentText("Test box")
        w._load_selected()
        self.assertEqual((w.host.text(), w.username.text(), w.password.text()), ("192.0.2.10", "someuser", "example-password"))
        self.assertTrue(w.remember.isChecked())

    def test_named_connection_for_another_user_does_not_get_the_servers_password(self):
        from freerdc import store
        from freerdc.model import Profile
        self.connect_to("192.0.2.10", "someuser", "example-password", remember=True)
        store.save_profile("Admin box", Profile(host="192.0.2.10", username="administrator"), False)
        w = self.w
        w._refresh_profiles(); w.saved.setCurrentText("Admin box"); w._load_selected()
        self.assertEqual(w.username.text(), "administrator")
        self.assertEqual(w.password.text(), "")
        self.assertFalse(w.remember.isChecked())

    def test_dropdown_pick_finds_the_password_saved_in_a_named_connection(self):
        from freerdc import store
        from freerdc.model import Profile
        store.save_profile("Test box", Profile(host="192.0.2.10", username="someuser", password="from-profile"), True)
        self.connect_to("192.0.2.10", "someuser", "", remember=False)  # a connect makes the server appear in the list
        self.connect_to("other", "bob", "pw", remember=False)
        self.w.password.clear(); self.w.remember.setChecked(False)
        self.pick("192.0.2.10")
        self.assertEqual(self.w.password.text(), "from-profile")
        self.assertTrue(self.w.remember.isChecked())

    def test_keyring_failure_when_saving_is_reported_and_the_connection_stands(self):
        self.kr.fail = True
        self.connect_to("h", "u", "pw", remember=True)
        self.assertIn("Password not saved", self.warnings)
        self.assertEqual(self.w.connect_btn.text(), "Connect")

    def test_keyring_failure_when_recalling_is_reported(self):
        self.connect_to("h", "u", "pw", remember=True)
        self.connect_to("x", "u", "pw", remember=False)
        self.kr.fail = True
        self.pick("h")
        self.assertIn("Saved password unavailable", self.warnings)
        self.assertEqual(self.w.password.text(), "")
        self.assertTrue(self.w.remember.isChecked())  # keep the saved entry on the next connect


@unittest.skipUnless(keyring, "keyring/PySide6 not installed")
class TrustedCertificateUiTest(unittest.TestCase):
    """A certificate trusted with 'Trust and remember' must still be trusted after a restart."""

    FP = "c1850042142eda127898a6f1161ed988a31f89a3eca2a26a30b23f382aaf8204"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        self.windows = []

    def tearDown(self):
        for w in self.windows:
            w.close()
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old
        self.tmp.cleanup()

    def new_window(self):
        from freerdc.ui.main_window import MainWindow
        w = MainWindow()  # a fresh window = a fresh start of the application
        self.windows.append(w)
        return w

    def type_host(self, w, host, port=3389):
        w.host.setText(host); w.port.setValue(port); w._refresh_trusted()

    def test_trusted_certificate_survives_a_restart(self):
        first = self.new_window()
        self.type_host(first, "192.0.2.10")
        first._remember_fingerprint(self.FP)  # what "Trust and remember" does
        self.assertEqual(first._trusted(), [self.FP])

        second = self.new_window()  # the next build / next launch
        self.assertEqual(second._trusted(), [])  # no host typed yet
        self.type_host(second, "192.0.2.10")
        self.assertEqual(second._trusted(), [self.FP])
        self.assertEqual(second._profile().trusted_fingerprints, [self.FP])  # reaches the command line

    def test_other_servers_are_not_affected(self):
        w = self.new_window()
        self.type_host(w, "192.0.2.10"); w._remember_fingerprint(self.FP)
        self.type_host(w, "192.0.2.99")
        self.assertEqual(w._trusted(), [])
        self.type_host(w, "192.0.2.10", port=3390)
        self.assertEqual(w._trusted(), [])

    def test_forget_selected_removes_it_for_good(self):
        w = self.new_window()
        self.type_host(w, "h"); w._remember_fingerprint(self.FP)
        w.trusted.item(0).setSelected(True)
        w._forget_trusted()
        self.assertEqual(w._trusted(), [])
        again = self.new_window(); self.type_host(again, "h")
        self.assertEqual(again._trusted(), [])

    def test_a_saved_connections_own_fingerprints_are_kept_alongside(self):
        from freerdc import store
        from freerdc.model import Profile
        w = self.new_window()
        self.type_host(w, "h"); w._remember_fingerprint(self.FP)
        w._apply(Profile(host="h", trusted_fingerprints=["dd" * 32]))
        self.assertEqual(sorted(w._trusted()), sorted([self.FP, "dd" * 32]))
        self.assertEqual(store.trusted_certificates("h", 3389), [self.FP])  # server list unchanged


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(keyring, "keyring/PySide6 not installed")
class DefaultsUiTest(RememberCredentialsUiTest):
    def test_defaults_apply_at_startup_and_on_selection(self):
        w = self.w
        self.assertEqual(w.saved.itemText(0), "(My defaults)")
        w.sound.setChecked(True)
        w.saved.setCurrentIndex(0)
        w._save()  # "(My defaults)" selected: Save updates the defaults
        from freerdc import store
        self.assertTrue(store.load_defaults()[0].sound)
        w.host.setText("keep.me"); w.sound.setChecked(False); w.fullscreen.setChecked(True)
        w._load_selected()  # pick "(My defaults)" again
        self.assertTrue(w.sound.isChecked())
        self.assertFalse(w.fullscreen.isChecked())
        self.assertEqual(w.host.text(), "keep.me")  # logon fields are untouched

    def test_new_window_starts_from_defaults(self):
        self.w.sound.setChecked(True)
        self.w._save_defaults()
        from freerdc.ui.main_window import MainWindow
        w2 = MainWindow()
        self.assertTrue(w2.sound.isChecked())
        w2.close()


@unittest.skipUnless(keyring, "keyring/PySide6 not installed")
class RecentOnlyOnSuccessTest(RememberCredentialsUiTest):
    def test_failed_new_server_is_not_listed_but_a_successful_one_is(self):
        from freerdc import store
        w = self.w
        w.host.setText("10.9.9.9"); w.username.setText("u"); w.password.setText("p")
        w._connect()  # the attempt starts, then fails: _on_connected is never reached
        self.assertEqual(store.recent_servers(), [])
        self.assertEqual(w.host.count(), 0)
        w._on_connected()
        self.assertEqual([e["host"] for e in store.recent_servers()], ["10.9.9.9"])

    def test_failure_of_a_known_server_leaves_it_alone(self):
        from freerdc import store
        self.connect_to("good.example", "u", "p", remember=False)
        before = store.recent_servers()
        w = self.w
        w.runner.running = lambda: False
        w._connect()  # known server, this time it fails
        self.assertEqual(store.recent_servers(), before)


@unittest.skipUnless(keyring, "keyring/PySide6 not installed")
class HideButtonTest(RememberCredentialsUiTest):
    def test_hide_button_only_while_connected(self):
        w = self.w
        w.show()
        self.assertTrue(w.hide_btn.isHidden())
        self.connect_to("10.1.1.1", "u", "p", remember=False)  # connects
        self.assertFalse(w.hide_btn.isHidden())
        w._on_finished(0, "", False)
        self.assertTrue(w.hide_btn.isHidden())


@unittest.skipUnless(keyring, "keyring/PySide6 not installed")
class StartupSelectionTest(RememberCredentialsUiTest):
    def test_most_recent_server_is_selected_at_startup(self):
        from freerdc import store
        from freerdc.ui.main_window import MainWindow
        self.assertEqual(self.w.host.text(), "")  # nothing recorded yet
        store.record_recent_server("old.example", 3389, "olduser")
        store.record_recent_server("new.example", 3390, "newuser")
        w2 = MainWindow()
        self.assertEqual((w2.host.text(), w2.port.value(), w2.username.text()),
                         ("new.example", 3390, "newuser"))
        w2.close()


@unittest.skipUnless(keyring, "keyring/PySide6 not installed")
class LogAndAdvancedLayoutTest(RememberCredentialsUiTest):
    def tab_row_fits(self):
        w = self.w
        QApplication.processEvents(); QApplication.processEvents()
        need = w.tabs.tabBar().sizeHint().width() + w.options_btn.sizeHint().width()
        self.assertGreaterEqual(w.tabs.width(), need, "the tab row is clipped")

    def test_advanced_gets_its_room_with_the_log_open_either_way_round(self):
        w = self.w
        w.show()
        w.show_log.setChecked(True)
        w._set_options_visible(True)
        self.tab_row_fits()
        self.assertGreaterEqual(w.log.width(), 520)
        w._set_options_visible(False)
        w.show_log.setChecked(False)
        w._set_options_visible(True)
        w.show_log.setChecked(True)
        self.tab_row_fits()
        self.assertGreaterEqual(w.log.width(), 520)
