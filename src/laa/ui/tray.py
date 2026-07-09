from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from laa.ui.assets import tray_icon
from laa.ui.main_window import MainWindow
from laa.ui.store import ConfigStore


def make_icon(paused: bool) -> QIcon:
    """The tray/window logo; dimmed when automation is paused."""
    return tray_icon(paused)


def create_tray(app: QApplication, window: MainWindow, store: ConfigStore) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(make_icon(store.get().master_paused), parent=app)
    menu = QMenu()
    pause = menu.addAction("Pause")
    pause.setCheckable(True)
    pause.setChecked(store.get().master_paused)

    def on_pause(checked: bool) -> None:
        store.update(master_paused=checked)
        tray.setIcon(make_icon(checked))
        # Reflect the change on the window button without re-firing its handler.
        window._pause.blockSignals(True)
        window._pause.setChecked(checked)
        window._pause.blockSignals(False)

    pause.toggled.connect(on_pause)

    def _sync_from_window(checked: bool) -> None:
        # Window button already wrote master_paused; mirror onto the tray
        # without re-firing on_pause.
        tray.setIcon(make_icon(checked))
        pause.blockSignals(True)
        pause.setChecked(checked)
        pause.blockSignals(False)

    window._pause.toggled.connect(_sync_from_window)
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
