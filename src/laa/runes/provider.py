from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

# ---- U.GG constants (community-reverse-engineered; verified by scripts/probe_ugg.py) ----
DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
UGG_OVERVIEW_URL = "https://stats2.u.gg/lol/1.5/overview/{version}/ranked_solo_5x5/{champion_id}/1.5.0.json"
REGION_WORLD = "12"
RANK_EMERALD_PLUS = "10"
ROLE_IDS = {"jungle": "1", "utility": "2", "bottom": "3", "top": "4", "middle": "5"}
IDX_PERKS = 0    # [matches, wins, primary_style, sub_style, [6 perk ids]]
IDX_SPELLS = 1   # [matches, wins, [2 spell ids]]
IDX_SHARDS = 8   # [matches, wins, [3 shard ids as strings]]
# -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Build:
    primary_style_id: int
    sub_style_id: int
    perk_ids: list[int]           # 6 runes + 3 stat shards, LCU order
    spell_ids: tuple[int, int]


def to_ugg_version(riot_version: str) -> str:
    major, minor, *_ = riot_version.split(".")
    return f"{major}_{minor}"


def parse_overview(data: dict, role: str) -> Build | None:
    try:
        rank = data[REGION_WORLD][RANK_EMERALD_PLUS]
        role_id = ROLE_IDS.get(role)
        if role_id not in rank:
            if not rank:
                return None
            role_id = max(rank, key=lambda r: rank[r][0][IDX_PERKS][0])  # most games played
        overview = rank[role_id][0]
        perks = overview[IDX_PERKS]
        spells = overview[IDX_SPELLS]
        shards = overview[IDX_SHARDS]
        return Build(
            primary_style_id=int(perks[2]),
            sub_style_id=int(perks[3]),
            perk_ids=[int(p) for p in perks[4]] + [int(s) for s in shards[2]],
            spell_ids=(int(spells[2][0]), int(spells[2][1])),
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class UGGProvider:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(timeout=5.0)
        self._version: str | None = None

    async def get_build(self, champion_id: int, role: str) -> Build | None:
        try:
            if self._version is None:
                resp = await self._http.get(DDRAGON_VERSIONS_URL)
                resp.raise_for_status()
                self._version = to_ugg_version(resp.json()[0])
            url = UGG_OVERVIEW_URL.format(version=self._version, champion_id=champion_id)
            resp = await self._http.get(url)
            resp.raise_for_status()
            build = parse_overview(resp.json(), role)
            if build is None:
                log.warning("U.GG payload for champion %s did not parse", champion_id)
            return build
        except Exception as exc:
            log.warning("Meta build fetch failed for champion %s: %s", champion_id, exc)
            self._version = None  # a stale patch version may 404; refetch next time
            return None
