from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from laa.ui.main_window import MainWindow
from laa.ui.store import ConfigStore


def make_icon(paused: bool) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#5b5a56") if paused else QColor("#c89b3c"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setPen(QColor("#0a1428"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(28)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "LA")
    painter.end()
    return QIcon(pm)


def create_tray(app: QApplication, window: MainWindow, store: ConfigStore) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(make_icon(store.get().master_paused), parent=app)
    menu = QMenu()
    pause = menu.addAction("Pause")
    pause.setCheckable(True)
    pause.setChecked(store.get().master_paused)

    def on_pause(checked: bool) -> None:
        store.update(master_paused=checked)
        tray.setIcon(make_icon(checked))

    pause.toggled.connect(on_pause)
    show = menu.addAction("Show window")
    show.triggered.connect(lambda: (window.showNormal(), window.activateWindow()))
    menu.addSeparator()
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray._menu = menu  # keep a python-side reference so the menu isn't GC'd
    tray.activated.connect(
        lambda reason: window.showNormal()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.setToolTip("League Auto Accept")
    tray.show()
    return tray
