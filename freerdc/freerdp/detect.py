"""Find installed FreeRDP clients and work out which major version each one is."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable, Optional

from ..environment import child_environment

# Distros disagree on names (Debian ships xfreerdp for 2.x and xfreerdp3 for 3.x,
# upstream 3.x calls it xfreerdp), so the version is always read from --version,
# never inferred from the file name.
CANDIDATE_NAMES = (
    "xfreerdp", "xfreerdp2", "xfreerdp3",
    "wlfreerdp", "wlfreerdp2", "wlfreerdp3",
    "sdl-freerdp", "sdl-freerdp3",
)

# Places a user-built FreeRDP commonly ends up that are often missing from a GUI app's PATH.
EXTRA_DIRS = (os.path.expanduser("~/.local/bin"), "/usr/local/bin", "/opt/freerdp/bin")

_VERSION_RE = re.compile(r"version\s+(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class FreeRDPClient:
    path: str
    major: int
    version: str
    flavor: str  # "x11" | "wayland" | "sdl"
    h264: bool = True  # does this build support the H.264 graphics codec? (distro builds vary)

    @property
    def label(self) -> str:
        return f"FreeRDP {self.version} ({self.flavor}) - {self.path}"


def _flavor(path: str) -> str:
    name = os.path.basename(path)
    if name.startswith("wl"):
        return "wayland"
    if name.startswith("sdl"):
        return "sdl"
    return "x11"


def _supports_h264(path: str, major: int) -> bool:
    """Ask the client's own help. FreeRDP 2 lists /gfx-h264 only when built with H.264; the
    FreeRDP 3 /gfx help names the AVC modes. If the help can't be read, assume yes."""
    try:
        out = subprocess.run([path, "/help"], capture_output=True, text=True, timeout=10,
                             env=child_environment())
    except (OSError, subprocess.SubprocessError):
        return True
    text = out.stdout + out.stderr
    if not text.strip():
        return True
    return ("AVC420" in text or "AVC444" in text) if major >= 3 else ("gfx-h264" in text)


def probe(path: str) -> Optional[FreeRDPClient]:
    """Run `<path> --version`; return None if it isn't a working FreeRDP client."""
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5,
                             env=child_environment())
    except (OSError, subprocess.SubprocessError):
        return None
    m = _VERSION_RE.search(out.stdout + out.stderr)
    if not m:
        return None
    major, minor, patch = (int(x) for x in m.groups())
    return FreeRDPClient(path, major, f"{major}.{minor}.{patch}", _flavor(path),
                         h264=_supports_h264(path, major))


def detect_clients(extra_paths: Iterable[str] = ()) -> list[FreeRDPClient]:
    """All distinct FreeRDP clients on PATH plus any user-supplied paths."""
    seen: set[str] = set()
    found: list[FreeRDPClient] = []
    search = os.pathsep.join([os.environ.get("PATH", ""), *EXTRA_DIRS])
    paths = [shutil.which(n, path=search) for n in CANDIDATE_NAMES] + list(extra_paths)
    for p in paths:
        if not p:
            continue
        real = os.path.realpath(p)
        if real in seen:
            continue
        seen.add(real)
        client = probe(p)
        if client:
            found.append(client)
    # Newest first; x11 before wayland before sdl (SDL is still marked experimental).
    order = {"x11": 0, "wayland": 1, "sdl": 2}
    return sorted(found, key=lambda c: (order[c.flavor], -c.major, c.path))
