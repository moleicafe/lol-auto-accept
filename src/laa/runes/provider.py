from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

# ---- op.gg constants (reverse-engineered; verified live by scripts/probe_opgg.py) -------
OPGG_URL = "https://lol-api-champion.op.gg/api/{region}/champions/ranked/{champion_id}/{position}"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# LCU assignedPosition -> op.gg position path segment
POSITION_MAP = {"top": "top", "jungle": "jungle", "middle": "mid",
                "bottom": "adc", "utility": "support"}
# op.gg summary.positions[].name -> op.gg position path segment (for primary-lane fallback)
PRIMARY_NAME_MAP = {"TOP": "top", "JUNGLE": "jungle", "MID": "mid",
                    "ADC": "adc", "SUPPORT": "support"}
DEFAULT_POSITION = "mid"  # last-resort when an unassigned champion's primary can't be read
# ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Build:
    primary_style_id: int
    sub_style_id: int
    perk_ids: list[int]           # 6 runes (4 primary + 2 secondary) + 3 stat shards, LCU order
    spell_ids: tuple[int, int]


def parse_champion(data: dict) -> Build | None:
    try:
        runes = data.get("runes") or []
        spells = data.get("summoner_spells") or []
        if not runes or not spells:
            return None
        top = max(runes, key=lambda r: r.get("play", 0))
        best_spells = max(spells, key=lambda s: s.get("play", 0))
        perk_ids = ([int(p) for p in top["primary_rune_ids"]]
                    + [int(p) for p in top["secondary_rune_ids"]]
                    + [int(p) for p in top["stat_mod_ids"]])
        spell_ids = (int(best_spells["ids"][0]), int(best_spells["ids"][1]))
        return Build(
            primary_style_id=int(top["primary_page_id"]),
            sub_style_id=int(top["secondary_page_id"]),
            perk_ids=perk_ids,
            spell_ids=spell_ids,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class OPGGProvider:
    def __init__(self, http: httpx.AsyncClient | None = None, region: str = "global") -> None:
        self._http = http or httpx.AsyncClient(timeout=5.0, headers={"User-Agent": USER_AGENT})
        self._region = region

    async def _fetch(self, champion_id: int, position: str) -> dict:
        url = OPGG_URL.format(region=self._region, champion_id=champion_id, position=position)
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.json()["data"]

    async def _primary_position(self, champion_id: int) -> str:
        data = await self._fetch(champion_id, DEFAULT_POSITION)
        positions = data.get("summary", {}).get("positions") or []
        if positions:
            return PRIMARY_NAME_MAP.get(positions[0].get("name", ""), DEFAULT_POSITION)
        return DEFAULT_POSITION

    async def get_build(self, champion_id: int, role: str) -> Build | None:
        try:
            position = POSITION_MAP.get(role)
            if position is None:  # unassigned / blind / ARAM -> use champion's primary lane
                position = await self._primary_position(champion_id)
            data = await self._fetch(champion_id, position)
            build = parse_champion(data)
            if build is None:
                log.warning("op.gg payload for champion %s did not parse", champion_id)
            return build
        except Exception as exc:
            log.warning("Meta build fetch failed for champion %s: %s", champion_id, exc)
            return None
