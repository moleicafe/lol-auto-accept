from __future__ import annotations

import dataclasses
import logging
import threading
from pathlib import Path

from laa import config as config_mod
from laa.config import Config

log = logging.getLogger(__name__)


class ConfigStore:
    """Thread-safe config holder. Readers grab an immutable-by-convention snapshot."""

    def __init__(self, cfg: Config, path: Path | None = None) -> None:
        self._cfg = cfg
        self._path = path
        self._lock = threading.Lock()

    def get(self) -> Config:
        return self._cfg

    def update(self, **changes) -> Config:
        with self._lock:
            self._cfg = dataclasses.replace(self._cfg, **changes)
            try:
                config_mod.save(self._cfg, self._path)
            except OSError as exc:
                log.warning("Failed to persist config: %s", exc)
            return self._cfg
