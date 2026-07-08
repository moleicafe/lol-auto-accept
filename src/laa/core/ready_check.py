from __future__ import annotations

import asyncio
import logging
from typing import Callable

from laa.config import Config
from laa.lcu.connector import LCUError
from laa.lcu.events import ReadyCheckUpdate

log = logging.getLogger(__name__)

ACCEPT_PATH = "/lol-matchmaking/v1/ready-check/accept"


class ReadyCheckAutomation:
    def __init__(self, lcu, get_config: Callable[[], Config]) -> None:
        self._lcu = lcu
        self._get_config = get_config
        self._handled = False

    def reset(self) -> None:
        self._handled = False

    async def on_update(self, update: ReadyCheckUpdate) -> None:
        cfg = self._get_config()
        if self._handled or cfg.master_paused or not cfg.auto_accept:
            return
        if update.state != "InProgress" or update.player_response != "None":
            return
        self._handled = True
        if cfg.accept_delay_s > 0:
            await asyncio.sleep(cfg.accept_delay_s)
            cfg = self._get_config()  # user may have paused during the delay
            if cfg.master_paused or not cfg.auto_accept:
                self._handled = False
                return
        try:
            await self._lcu.post(ACCEPT_PATH)
            log.info("Ready check accepted")
        except LCUError as exc:
            log.warning("Accept failed: %s", exc)
            self._handled = False
