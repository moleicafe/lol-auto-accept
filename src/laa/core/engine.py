from __future__ import annotations

import logging
from typing import Callable

from laa.config import Config
from laa.core.champ_select import ChampSelectAutomation
from laa.core.ready_check import ReadyCheckAutomation
from laa.lcu import events

log = logging.getLogger(__name__)


class Engine:
    """Routes LCU events to automations; owns phase tracking and resets."""

    def __init__(self, lcu, get_config: Callable[[], Config], catalog, rune_applier,
                 notify: Callable[[str], None] | None = None) -> None:
        self._lcu = lcu
        self._catalog = catalog
        self._notify = notify or (lambda text: None)
        self._ready = ReadyCheckAutomation(lcu, get_config)
        self._champ = ChampSelectAutomation(lcu, get_config, on_locked=rune_applier.apply)
        self.phase = ""

    async def on_event(self, event: events.LCUEvent) -> None:
        try:
            await self._dispatch(event)
        except Exception:
            log.exception("Engine error handling %s", type(event).__name__)

    async def _dispatch(self, event: events.LCUEvent) -> None:
        match event:
            case events.Connected():
                await self._catalog.refresh()
                phase = await self._lcu.get("/lol-gameflow/v1/gameflow-phase")
                if isinstance(phase, str):
                    self._set_phase(phase)
                self._notify("Connected")
            case events.Disconnected():
                self._notify("Waiting for League client")
            case events.GameflowPhase(phase=phase):
                self._set_phase(phase)
            case events.ReadyCheckUpdate() as update:
                await self._ready.on_update(update)
            case events.ChampSelectUpdate(session=session):
                await self._champ.on_session(session)

    def _set_phase(self, phase: str) -> None:
        if phase == self.phase:
            return
        if phase != "ReadyCheck":
            self._ready.reset()
        if phase != "ChampSelect":
            self._champ.reset()
        self.phase = phase
        self._notify(phase)
