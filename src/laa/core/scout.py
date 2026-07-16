"""Builds an op.gg multisearch URL for the current champ-select lobby.

Qt-free. The engine feeds it champ-select sessions; the UI (via the worker)
asks it for a URL on demand, and it can auto-produce one once per champ select
when `multisearch_auto` is enabled.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Callable

from laa.config import Config
from laa.lcu.connector import LCUError

log = logging.getLogger(__name__)

MULTISEARCH_URL = "https://op.gg/multisearch/{region}?summoners={summoners}"
DEFAULT_REGION = "na"


class LobbyScout:
    def __init__(self, lcu, get_config: Callable[[], Config]) -> None:
        self._lcu = lcu
        self._get_config = get_config
        self._session: dict | None = None
        self._auto_done = False

    def reset(self) -> None:
        self._session = None
        self._auto_done = False

    def update_session(self, session: dict) -> None:
        self._session = session

    async def maybe_auto_url(self, session: dict) -> str | None:
        """Auto-scout hook: returns a URL once per champ select when enabled."""
        self.update_session(session)
        cfg = self._get_config()
        if not cfg.multisearch_auto or cfg.master_paused or self._auto_done:
            return None
        url = await self.build_url()
        if url is not None:
            self._auto_done = True
        return url

    async def build_url(self) -> str | None:
        session = self._session
        if not isinstance(session, dict):
            return None
        local = session.get("localPlayerCellId")
        ally_ids = [m.get("summonerId") for m in (session.get("myTeam") or [])
                    if m.get("cellId") != local and m.get("summonerId")]
        if not ally_ids:
            log.info("Scout lobby: no ally names available")
            return None
        riot_ids: list[str] = []
        for sid in ally_ids:
            try:
                s = await self._lcu.get(f"/lol-summoner/v2/summoners/{sid}") or {}
                name, tag = s.get("gameName"), s.get("tagLine")
                if name and tag:
                    riot_ids.append(f"{name}#{tag}")
            except LCUError as exc:
                log.debug("Scout lobby: lookup failed for %s: %s", sid, exc)
        if not riot_ids:
            log.info("Scout lobby: no ally names available")
            return None
        region = DEFAULT_REGION
        try:
            locale = await self._lcu.get("/riotclient/region-locale") or {}
            region = (locale.get("region") or DEFAULT_REGION).lower()
        except LCUError:
            pass
        return MULTISEARCH_URL.format(
            region=region, summoners=urllib.parse.quote(",".join(riot_ids), safe=""))
