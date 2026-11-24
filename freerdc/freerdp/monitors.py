"""List the monitors a FreeRDP client can see, to help fill in the Monitors field."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from ..environment import child_environment
from .detect import FreeRDPClient

# "  * [0] 1920x1080\t+0+0"  (X11, Wayland, FreeRDP 2)
# "  * [1] [Virtual-1] 1920x1080\t+0+0"  (SDL client: 1-based, with the output name)
_LINE = re.compile(r"^\s*(\*)?\s*\[(\d+)\]\s*(?:\[([^\]]*)\])?\s*(\d+)x(\d+)\s+([+-]\d+)([+-]\d+)")
_LOG_LINE = re.compile(r"^\[\d\d:\d\d:\d\d:\d+\]")  # "[19:13:26:955] [pid:tid] [WARN]..."


@dataclass(frozen=True)
class MonitorInfo:
    id: int
    width: int
    height: int
    x: int
    y: int
    primary: bool = False
    name: str = ""

    def describe(self) -> str:
        label = f"Monitor {self.id}" + (f" [{self.name}]" if self.name else "")
        pos = f"{self.x:+d}{self.y:+d}"
        return f"{label}: {self.width}x{self.height} at {pos}" + ("  (primary)" if self.primary else "")


def monitor_list_command(client: FreeRDPClient) -> list[str]:
    # The option was renamed: FreeRDP 2 has /monitor-list, 3.x has /list:monitor (singular;
    # /list:monitors is rejected with a usage error).
    return [client.path, "/list:monitor" if client.major >= 3 else "/monitor-list"]


def parse_monitor_list(text: str) -> list[MonitorInfo]:
    out = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            star, ident, name, w, h, x, y = m.groups()
            out.append(MonitorInfo(int(ident), int(w), int(h), int(x), int(y), bool(star), name or ""))
    return out


def detect_monitors(client: FreeRDPClient, timeout: float = 15.0) -> tuple[list[MonitorInfo], str]:
    """Run the client's monitor listing. Returns (monitors, raw output); raises OSError or
    subprocess.TimeoutExpired if the client cannot be run."""
    proc = subprocess.run(monitor_list_command(client), capture_output=True, text=True,
                          timeout=timeout, env=child_environment())
    raw = (proc.stdout + proc.stderr).strip()
    monitors = parse_monitor_list(raw)
    if monitors:  # drop FreeRDP's "deprecated/experimental client" log lines; keep all on failure
        raw = "\n".join(l for l in raw.splitlines() if not _LOG_LINE.match(l)).strip()
    return monitors, raw
