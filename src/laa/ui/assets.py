"""Loads the app logo (assets/logo.png) as Qt icons/pixmaps.

Resolves the image both when running from source and when frozen by
PyInstaller (via ``sys._MEIPASS``). Falls back to a plain gold disc if the
file is missing, so callers always get a non-null icon.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

_LOGO_REL = "assets/logo.png"


def _logo_path() -> Path:
    base = getattr(sys, "_MEIPASS", None)  # set when frozen by PyInstaller
    if base:
        return Path(base) / _LOGO_REL
    return Path(__file__).resolve().parents[3] / _LOGO_REL  # project root


def _fallback_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#c89b3c"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.end()
    return pm


def logo_pixmap(size: int = 256) -> QPixmap:
    path = _logo_path()
    pm = QPixmap(str(path)) if path.exists() else QPixmap()
    if pm.isNull():
        return _fallback_pixmap(size)
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


def logo_icon() -> QIcon:
    return QIcon(logo_pixmap(256))


def tray_icon(paused: bool = False) -> QIcon:
    """The logo for the system tray; dimmed when automation is paused."""
    pm = logo_pixmap(64)
    if not paused:
        return QIcon(pm)
    faded = QPixmap(pm.size())
    faded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faded)
    painter.setOpacity(0.35)
    painter.drawPixmap(0, 0, pm)
    painter.end()
    return QIcon(faded)
