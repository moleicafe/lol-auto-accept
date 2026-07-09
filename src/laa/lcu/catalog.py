from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SUMMARY_PATH = "/lol-game-data/assets/v1/champion-summary.json"


class ChampionCatalog:
    def __init__(self, lcu) -> None:
        self._lcu = lcu
        self._by_id: dict[int, str] = {}

    async def refresh(self) -> None:
        data = await self._lcu.get(SUMMARY_PATH) or []
        self._by_id = {c["id"]: c["name"] for c in data if c.get("id", -1) > 0}
        log.info("Champion catalog loaded: %d champions", len(self._by_id))

    def name(self, champion_id: int) -> str:
        return self._by_id.get(champion_id, f"#{champion_id}")

    def all(self) -> dict[int, str]:
        return dict(self._by_id)
