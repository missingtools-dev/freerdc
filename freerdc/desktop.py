"""Add FreeRDC to (or remove it from) the current user's application menu.

Works from any build, including a single-file one, because the icons come from the
application's own bundled assets and the entry points at the running executable."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "FreeRDC"


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _exec_line() -> str:
    if getattr(sys, "frozen", False):  # a PyInstaller bundle: the executable is the program
        return shlex.quote(os.path.realpath(sys.executable))
    return f"{shlex.quote(sys.executable)} -m freerdc"


def _entry() -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={NAME}",
        "GenericName=RDP client",
        "Comment=Connect to Windows computers with FreeRDP",
        f"Exec={_exec_line()}",
        "Icon=freerdc",
        "Terminal=false",
        "Categories=Network;RemoteAccess;",
        "Keywords=rdp;remote;desktop;freerdp;",
        "StartupWMClass=freerdc",
        "",
    ])


def _refresh(data: Path) -> None:
    for cmd in (["update-desktop-database", str(data / "applications")],
                ["gtk-update-icon-cache", "-q", str(data / "icons" / "hicolor")]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass  # optional: menus pick the files up on their own


def install() -> Path:
    data = _data_home()
    assets = Path(__file__).resolve().parent / "assets"
    for png in sorted(assets.glob("freerdc-*.png")):
        size = png.stem.removeprefix("freerdc-")
        target = data / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(png, target / "freerdc.png")
    apps = data / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "freerdc.desktop"
    entry.write_text(_entry())
    _refresh(data)
    return entry


def uninstall() -> list[Path]:
    data = _data_home()
    removed = []
    for path in [data / "applications" / "freerdc.desktop",
                 *(data / "icons" / "hicolor").glob("*/apps/freerdc.png")]:
        if path.exists():
            path.unlink()
            removed.append(path)
    _refresh(data)
    return removed
