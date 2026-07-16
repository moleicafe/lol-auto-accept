from __future__ import annotations

import logging
import time
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
    skill_max: list[str] = field(default_factory=list, compare=False)    # e.g. ["Q","W","E"]
    skill_start: list[str] = field(default_factory=list, compare=False)  # first 4 levels
    counter_ids: list[tuple[int, float]] = field(default_factory=list, compare=False)


COUNTER_MIN_PLAY = 20  # ignore low-sample counter matchups
COUNTER_TOP_N = 3
CACHE_TTL_S = 600.0  # provider fetch-cache lifetime (covers one champ select)


def _parse_counters(data: dict) -> list[tuple[int, float]]:
    try:
        entries = [e for e in (data.get("counters") or [])
                   if e.get("play", 0) >= COUNTER_MIN_PLAY]
        rated = [(int(e["champion_id"]), e.get("win", 0) / e["play"]) for e in entries]
        rated.sort(key=lambda t: t[1], reverse=True)
        return rated[:COUNTER_TOP_N]
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return []


def _parse_skill_order(data: dict) -> tuple[list[str], list[str]]:
    try:
        masteries = data.get("skill_masteries") or []
        skills = data.get("skills") or []
        skill_max = []
        if masteries:
            best = max(masteries, key=lambda e: e.get("play", 0))
            skill_max = [str(s) for s in best.get("ids", [])]
        skill_start = []
        if skills:
            best = max(skills, key=lambda e: e.get("play", 0))
            skill_start = [str(s) for s in best.get("order", [])][:4]
        return skill_max, skill_start
    except (KeyError, TypeError, ValueError):
        return [], []


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
        skill_max, skill_start = _parse_skill_order(data)
        return Build(
            primary_style_id=int(top["primary_page_id"]),
            sub_style_id=int(top["secondary_page_id"]),
            perk_ids=perk_ids,
            spell_ids=spell_ids,
            items=items,
            skill_max=skill_max,
            skill_start=skill_start,
            counter_ids=_parse_counters(data),
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class OPGGProvider:
    def __init__(self, http: httpx.AsyncClient | None = None, region: str = "global") -> None:
        self._http = http or httpx.AsyncClient(timeout=5.0, headers={"User-Agent": USER_AGENT})
        self._region = region
        # Size-1 cache: the counter-suggestion fetch at champ-select start and the
        # rune/item fetch at lock-in are usually the same champion+position. TTL
        # keeps a long-running tray app from serving stale meta across games.
        self._last: tuple[tuple[int, str], dict, float] | None = None

    async def _fetch(self, champion_id: int, position: str) -> dict:
        key = (champion_id, position)
        now = time.monotonic()
        if (self._last is not None and self._last[0] == key
                and now - self._last[2] < CACHE_TTL_S):
            return self._last[1]
        url = OPGG_URL.format(region=self._region, champion_id=champion_id, position=position)
        resp = await self._http.get(url)
        resp.raise_for_status()
        data = resp.json()["data"]
        self._last = (key, data, now)
        return data

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
