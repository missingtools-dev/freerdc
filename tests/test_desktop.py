import os
import tempfile
import unittest
from unittest import mock

from freerdc import desktop


class DesktopEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"XDG_DATA_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        refresh = mock.patch.object(desktop, "_refresh")
        refresh.start()
        self.addCleanup(refresh.stop)

    def test_install_writes_entry_and_icons_then_uninstall_removes_them(self):
        entry = desktop.install()
        text = entry.read_text()
        self.assertIn("Name=FreeRDC", text)
        self.assertIn("Icon=freerdc", text)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "icons/hicolor/48x48/apps/freerdc.png")))
        self.assertTrue(desktop.uninstall())
        self.assertFalse(entry.exists())

    def test_frozen_build_points_at_its_own_executable(self):
        with mock.patch.object(desktop.sys, "frozen", True, create=True), \
                mock.patch.object(desktop.sys, "executable", "/opt/my apps/freerdc"):
            self.assertIn("Exec='/opt/my apps/freerdc'\n", desktop._entry())


if __name__ == "__main__":
    unittest.main()
