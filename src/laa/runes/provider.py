from __future__ import annotations

import logging
from dataclasses import dataclass, field

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
SITUATIONAL_COUNT = 6  # how many late-game items to include in the Situational block
# ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemBuild:
    starter_ids: list[int]
    core_ids: list[int]
    boots_ids: list[int]
    situational_ids: list[int]

    def is_empty(self) -> bool:
        return not (self.starter_ids or self.core_ids
                    or self.boots_ids or self.situational_ids)


def _top_item_ids(entries) -> list[int]:
    entries = entries or []
    if not entries:
        return []
    best = max(entries, key=lambda e: e.get("play", 0))
    return [int(i) for i in best.get("ids", [])]


def parse_item_build(data: dict) -> ItemBuild:
    starter = _top_item_ids(data.get("starter_items"))
    core = _top_item_ids(data.get("core_items"))
    boots = _top_item_ids(data.get("boots"))
    shown = set(starter) | set(core) | set(boots)
    situational: list[int] = []
    for entry in sorted(data.get("last_items") or [],
                        key=lambda e: e.get("play", 0), reverse=True):
        for raw in entry.get("ids", []):
            iid = int(raw)
            if iid not in shown and iid not in situational:
                situational.append(iid)
        if len(situational) >= SITUATIONAL_COUNT:
            break
    return ItemBuild(starter, core, boots, situational[:SITUATIONAL_COUNT])


@dataclass(frozen=True)
class Build:
    primary_style_id: int
    sub_style_id: int
    perk_ids: list[int]           # 6 runes (4 primary + 2 secondary) + 3 stat shards, LCU order
    spell_ids: tuple[int, int]
    items: "ItemBuild | None" = field(default=None, compare=False)


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
        try:
            items = parse_item_build(data)
        except (KeyError, IndexError, TypeError, ValueError):
            items = None
        return Build(
            primary_style_id=int(top["primary_page_id"]),
            sub_style_id=int(top["secondary_page_id"]),
            perk_ids=perk_ids,
            spell_ids=spell_ids,
            items=items,
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
