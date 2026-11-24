"""Render freerdc/assets/freerdc.svg to the PNG sizes the app and the .desktop file use.
Run: .venv/bin/python packaging/make_icons.py"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

assets = Path(__file__).resolve().parent.parent / "freerdc" / "assets"
app = QGuiApplication([])
renderer = QSvgRenderer(str(assets / "freerdc.svg"))
for size in (16, 24, 32, 48, 64, 128, 256):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    image.save(str(assets / f"freerdc-{size}.png"))
print("wrote", sorted(p.name for p in assets.glob("*.png")))
