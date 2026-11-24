import sys

from PySide6.QtWidgets import QApplication

from . import __version__
from .ui.main_window import MainWindow
from .ui.theme import app_icon, apply_theme


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"FreeRDC {__version__}")
        return 0
    if "--self-test" in sys.argv[1:]:
        from .selftest import run
        return run()
    if "--install-desktop" in sys.argv[1:]:
        from .desktop import install
        print(f"Installed: {install()}")
        return 0
    if "--uninstall-desktop" in sys.argv[1:]:
        from .desktop import uninstall
        print("Removed:", *uninstall() or ["nothing to remove"])
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("freerdc")
    app.setDesktopFileName("freerdc")  # lets Wayland/GNOME/KDE match the window to freerdc.desktop
    app.setWindowIcon(app_icon())
    apply_theme(app)  # same look on every distro, whatever the desktop theme
    # The window may be hidden while a session runs; only closing it should end the app.
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
