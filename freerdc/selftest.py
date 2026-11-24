"""`freerdc --self-test`: check that this installation can actually run on this machine.

Used to verify a packaged build on a new distro. It starts the real window code, then
reports Qt, the keyring and each FreeRDP client found, including whether that client's help
lists every option freerdc passes to it (older FreeRDP releases may lack some).
"""
from __future__ import annotations

import os
import subprocess
import sys

from .environment import child_environment

# Options freerdc puts on the command line (see freerdp/args.py). Matched by name only:
# FreeRDP treats "+name" and "/name" as the same switch and its help may use either.
COMMON_FLAGS = ["v:", "u:", "d:", "p:", "size", "bpp", "monitors", "multimon",
                "dynamic-resolution", "smart-sizing", "sound", "microphone", "drive",
                "home-drive", "gfx", "auto-reconnect", "auto-reconnect-max-retries",
                "sec", "cert", "fingerprint", "floatbar", "log-level"]
V2_FLAGS = ["clipboard", "from-stdin", "monitor-list", "gfx-h264"]
V3_FLAGS = ["clipboard", "args-from", "list:", "monitor"]


def _help_text(path: str) -> str:
    try:
        proc = subprocess.run([path, "/help"], capture_output=True, text=True, timeout=15,
                              env=child_environment())
        return proc.stdout + proc.stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def run() -> int:
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication

    from . import __version__, store
    from .freerdp import detect_clients
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.processEvents()
    print(f"FreeRDC {__version__} | python {sys.version.split()[0]} | PySide6 {pyside_version} | Qt {qVersion()} "
          f"| platform plugin: {app.platformName()}")
    print(f"window created: {window.size().width()}x{window.size().height()}")
    try:
        import keyring
        backend = type(keyring.get_keyring()).__module__
    except Exception as e:  # noqa: BLE001 - report whatever went wrong
        backend = f"unavailable ({e})"
    print(f"keyring backend: {backend} | usable: {store.keyring_available()}")
    clients = detect_clients(store.client_paths())
    if not clients:
        print("FreeRDP clients: none found")
    for c in clients:
        wanted = COMMON_FLAGS + (V3_FLAGS if c.major >= 3 else V2_FLAGS)
        text = _help_text(c.path)
        missing = [f for f in wanted if f not in text] if text else ["(could not read /help)"]
        print(f"FreeRDP {c.version} ({c.flavor}) {c.path}: "
              + ("all options freerdc uses are listed" if not missing else f"NOT listed: {missing}"))
    host = os.environ.get("FREERDC_TEST_HOST")
    if host and clients:
        _connection_tests(app, window, clients, host, os.environ.get("FREERDC_TEST_USER", ""),
                          os.environ.get("FREERDC_TEST_PASSWORD", ""))
    window.close()
    return 0


def _connection_tests(app, window, clients, host: str, user: str, password: str) -> None:
    """Really connect with every client found (FREERDC_TEST_HOST / _USER / _PASSWORD), once with
    default options and once with many options set, then disconnect. Prints one line each."""
    import time

    from PySide6.QtWidgets import QMessageBox

    from .model import Drive, Floatbar, Profile

    dialogs: list[str] = []  # never block on a dialog: record it
    QMessageBox.exec = lambda self: dialogs.append(f"{self.windowTitle()}: {self.text()}")
    QMessageBox.warning = staticmethod(lambda parent, title, text, *a: dialogs.append(f"{title}: {text}") or 0)
    window.hide_on_connect.setChecked(False)
    window.timeout_spin.setValue(40)

    def pump(condition, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.1)
            if condition():
                return True
        return False

    def idle() -> bool:
        return window.connect_btn.text() == "Connect" and not window.runner.running()

    scenarios = {
        "default options": dict(),
        "many options": dict(
            width=1280, height=720, color_depth=32, dynamic_resolution=False, smart_sizing=True,
            sound=True, microphone=True, home_drive=True, drives=[Drive("tmp", "/tmp")],
            security="nla", gfx_h264="AVC444", auto_reconnect_retries=3,
            floatbar=Floatbar(sticky=False, default_visible=False, show="fullscreen")),
    }
    for index, client in enumerate(clients):
        if client.flavor == "wayland" and not os.environ.get("WAYLAND_DISPLAY"):
            print(f"[{client.version} {client.flavor}] skipped: no Wayland session")
            continue
        window.client_combo.setCurrentIndex(index)
        for label, extra in scenarios.items():
            dialogs.clear()
            window._apply(Profile(host=host, username=user, password=password,
                                  cert_mode="any", **extra))
            window.remember.setChecked(False)  # a test must not touch the keyring
            command = window.preview.toPlainText().replace(client.path, "<client>")
            started = time.monotonic()
            window._connect()
            up = pump(lambda: window.connect_btn.text() == "Disconnect" or idle(), 50) \
                and window.connect_btn.text() == "Disconnect"
            took = time.monotonic() - started
            status = window.status.text()
            if up:
                pump(lambda: False, 3)  # let the desktop come up for a moment
                window._connect()       # Disconnect
                pump(idle, 30)
            note = f" | dialog: {dialogs[0][:110]}" if dialogs else ""
            print(f"[{client.version} {client.flavor:7}] {label:15}: "
                  f"{'CONNECTED' if up else 'NOT CONNECTED'} in {took:4.1f}s | {status}{note}", flush=True)
            print(f"      command: {command}", flush=True)
