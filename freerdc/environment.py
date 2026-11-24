"""The environment for programs freerdc launches (FreeRDP, stdbuf)."""
from __future__ import annotations

import os
import sys


def child_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """A PyInstaller bundle puts its own copies of system libraries (OpenSSL, zlib, libstdc++,
    ...) first on LD_LIBRARY_PATH. Programs started from the app inherit that and then load
    the bundle's libraries instead of their own, which fails with symbol errors when the
    bundle was built on an older distro than the one it runs on (FreeRDP 3 crashes this way).
    The bootloader keeps the user's original value in LD_LIBRARY_PATH_ORIG; restore it."""
    env = dict(os.environ if env is None else env)
    if getattr(sys, "frozen", False):
        for var in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
            original = env.pop(f"{var}_ORIG", None)
            if original:
                env[var] = original
            elif var == "LD_LIBRARY_PATH":
                env.pop(var, None)  # it was unset before the bundle started
    return env
