import unittest
from pathlib import Path

from freerdc.freerdp import session_established

FIXTURES = Path(__file__).parent / "fixtures"  # trimmed real output of FreeRDP 2.11.7 / 3.15.0


def log(name: str) -> str:
    return (FIXTURES / f"{name}.log").read_text()


class SessionTest(unittest.TestCase):
    def test_successful_login_is_detected(self):
        self.assertTrue(session_established(log("ok3")))  # FreeRDP 3
        self.assertTrue(session_established(log("ok2")))  # FreeRDP 2

    def test_failed_login_is_not(self):
        self.assertFalse(session_established(log("bad3")))
        self.assertFalse(session_established(log("bad2")))

    def test_each_marker_alone_is_enough(self):
        self.assertTrue(session_established("[INFO][com.freerdp.gdi] - Local framebuffer format  X"))
        self.assertTrue(session_established("[INFO] - [dvcman_load_addin]: Loading Dynamic Virtual Channel disp"))

    def test_connection_progress_alone_is_not(self):
        self.assertFalse(session_established("[WARN] license binary blob::type BB_ERROR_BLOB"))


if __name__ == "__main__":
    unittest.main()
