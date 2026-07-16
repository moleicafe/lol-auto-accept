"""Post-game automations: auto-honor a teammate, auto play-again.

Driven by gameflow phases (PreEndOfGame -> honor ballot; EndOfGame -> play again).
Each fires at most once per game; the engine resets this automation when the
gameflow leaves the end-of-game phases.
"""
from __future__ import annotations

import logging
import random
from typing import Callable, Sequence

from laa.config import Config
from laa.lcu.connector import LCUError

log = logging.getLogger(__name__)

BALLOT_PATH = "/lol-honor-v2/v1/ballot"
HONOR_PATH = "/lol-honor-v2/v1/honor-player"
PLAY_AGAIN_PATH = "/lol-lobby/v2/play-again"


class EndOfGameAutomation:
    def __init__(self, lcu, get_config: Callable[[], Config],
                 choose: Callable[[Sequence], object] = random.choice) -> None:
        self._lcu = lcu
        self._get_config = get_config
        self._choose = choose
        self.reset()

    def reset(self) -> None:
        self._honored = False
        self._played_again = False

    async def on_phase(self, phase: str) -> None:
        cfg = self._get_config()
        if cfg.master_paused:
            return
        if phase == "PreEndOfGame" and cfg.auto_honor and not self._honored:
            await self._honor()
        elif phase == "EndOfGame" and cfg.auto_play_again and not self._played_again:
            await self._play_again()

    async def _honor(self) -> None:
        self._honored = True  # one attempt per game, even if it fails
        try:
            ballot = await self._lcu.get(BALLOT_PATH) or {}
            allies = ballot.get("eligibleAllies")
            if allies is None:  # older schema fallback
                allies = ballot.get("eligiblePlayers") or []
            if not allies:
                log.info("Auto-honor: no eligible teammates")
                return
            pick = self._choose(allies)
            body = {"summonerId": pick.get("summonerId"), "honorCategory": "HEART"}
            if pick.get("puuid"):
                body["puuid"] = pick["puuid"]
            await self._lcu.post(HONOR_PATH, body)
            log.info("Auto-honored teammate %s", pick.get("summonerId"))
        except (LCUError, KeyError, TypeError, AttributeError) as exc:
            log.warning("Auto-honor failed: %s", exc)

    async def _play_again(self) -> None:
        self._played_again = True
        try:
            await self._lcu.post(PLAY_AGAIN_PATH)
            log.info("Play again: returned to lobby")
        except LCUError as exc:
            log.warning("Play again failed: %s", exc)
