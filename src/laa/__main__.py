from __future__ import annotations

import ctypes
import logging
import logging.handlers
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from laa import config
from laa.ui.assets import logo_icon
from laa.ui.bridge import Bridge, QtLogHandler
from laa.ui.main_window import MainWindow
from laa.ui.store import ConfigStore
from laa.ui.tray import create_tray
from laa.ui.worker import LCUWorker

MUTEX_NAME = "Local\\LeagueAutoAcceptPy"
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def setup_logging() -> None:
    config.config_dir().mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        config.config_dir() / "laa.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


def main() -> int:
    # Make Windows group the taskbar entry under our own app id so it shows
    # the app icon rather than the generic Python one.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MUTEX_NAME)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setWindowIcon(logo_icon())
    if not acquire_single_instance():
        QMessageBox.warning(None, "League Auto Accept", "League Auto Accept is already running.")
        return 1
    setup_logging()
    app.setQuitOnLastWindowClosed(False)

    store = ConfigStore(config.load())
    bridge = Bridge()
    logging.getLogger("laa").addHandler(QtLogHandler(bridge))

    window = MainWindow(store, bridge)
    window.tray = create_tray(app, window, store)
    LCUWorker(store, bridge).start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
