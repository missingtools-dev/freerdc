"""One look on every distro: the Fusion style with a fixed light palette.

Without this Qt borrows the desktop's theme (GTK, Kvantum, a dark palette...), and
widgets such as check boxes come out faint or invisible on some of them."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

ACCENT = "#0078d7"  # the Windows 10 blue
BORDER = "#5a5a5a"


def _palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: "#f0f0f0", QPalette.WindowText: "#000000",
        QPalette.Base: "#ffffff", QPalette.AlternateBase: "#f5f5f5",
        QPalette.Text: "#000000", QPalette.Button: "#e1e1e1",
        QPalette.ButtonText: "#000000", QPalette.BrightText: "#ffffff",
        QPalette.ToolTipBase: "#ffffe1", QPalette.ToolTipText: "#000000",
        QPalette.Highlight: ACCENT, QPalette.HighlightedText: "#ffffff",
        QPalette.Link: ACCENT, QPalette.PlaceholderText: "#707070",
        QPalette.Light: "#ffffff", QPalette.Midlight: "#e3e3e3",
        QPalette.Mid: "#a0a0a0", QPalette.Dark: "#787878", QPalette.Shadow: "#696969",
    }
    for role, colour in roles.items():
        p.setColor(role, QColor(colour))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#8a8a8a"))
    return p


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_palette())
    icons = Path(tempfile.mkdtemp(prefix="freerdc-theme-"))
    tick, tick_off = icons / "tick.png", icons / "tick-disabled.png"
    for path, colour in ((tick, "#000000"), (tick_off, "#8a8a8a")):
        pm = QPixmap(28, 28)
        pm.fill(Qt.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(QPen(QColor(colour), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        qp.drawPolyline([QPointF(x, y) for x, y in ((5, 14), (11, 21), (23, 7))])
        qp.end()
        pm.save(str(path))
    app.setStyleSheet(f"""
        QCheckBox::indicator, QGroupBox::indicator {{
            width: 14px; height: 14px; border: 1px solid {BORDER};
            background: #ffffff; border-radius: 2px; }}
        QCheckBox::indicator:hover, QGroupBox::indicator:hover {{ border-color: {ACCENT}; }}
        QCheckBox::indicator:checked, QGroupBox::indicator:checked {{
            image: url({tick.as_posix()}); }}
        QCheckBox::indicator:disabled, QGroupBox::indicator:disabled {{
            border-color: #b4b4b4; background: #f0f0f0; }}
        QCheckBox::indicator:checked:disabled, QGroupBox::indicator:checked:disabled {{
            image: url({tick_off.as_posix()}); }}
    """)


def app_icon() -> QIcon:
    """The freerdc icon (a monitor with the hare badge), in every size we ship."""
    icon = QIcon()
    for png in sorted((Path(__file__).resolve().parent.parent / "assets").glob("freerdc-*.png")):
        icon.addFile(str(png))
    return icon
