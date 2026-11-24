import sys
import unittest
from unittest import mock

from freerdc.environment import child_environment


class ChildEnvironmentTest(unittest.TestCase):
    def test_unchanged_when_not_bundled(self):
        env = {"LD_LIBRARY_PATH": "/some/dir", "PATH": "/usr/bin"}
        self.assertEqual(child_environment(env), env)

    def test_bundled_app_restores_the_original_library_path(self):
        env = {"LD_LIBRARY_PATH": "/bundle/_internal", "LD_LIBRARY_PATH_ORIG": "/opt/lib:/usr/lib", "PATH": "/usr/bin"}
        with mock.patch.object(sys, "frozen", True, create=True):
            out = child_environment(env)
        self.assertEqual(out["LD_LIBRARY_PATH"], "/opt/lib:/usr/lib")
        self.assertNotIn("LD_LIBRARY_PATH_ORIG", out)
        self.assertEqual(out["PATH"], "/usr/bin")

    def test_bundled_app_drops_the_variable_if_it_was_not_set_originally(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            out = child_environment({"LD_LIBRARY_PATH": "/bundle/_internal"})
        self.assertNotIn("LD_LIBRARY_PATH", out)

    def test_does_not_modify_the_real_environment(self):
        import os
        before = dict(os.environ)
        with mock.patch.object(sys, "frozen", True, create=True):
            child_environment()
        self.assertEqual(dict(os.environ), before)


if __name__ == "__main__":
    unittest.main()
