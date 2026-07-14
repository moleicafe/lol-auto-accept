from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    """Signals crossing from the asyncio worker thread into the Qt main thread."""

    status = Signal(str)
    log_line = Signal(str)
    catalog_ready = Signal(object)  # dict[int, str]
    update_available = Signal(str, str)  # version, release url


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: Bridge) -> None:
        super().__init__(level=logging.INFO)
        self._bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._bridge.log_line.emit(self.format(record))
        except RuntimeError:
            pass  # bridge deleted during shutdown
