from __future__ import annotations

import logging
from typing import Callable

from laa.config import Config
from laa.core.selection import ordered_spells
from laa.lcu.connector import LCUError
from laa.runes.provider import Build, ItemBuild

log = logging.getLogger(__name__)

PAGE_PREFIX = "LAA:"


def _item_block(block_type: str, ids: list[int]) -> dict:
    return {"type": block_type, "items": [{"id": str(i), "count": 1} for i in ids]}


def core_block_title(skill_max: list[str], skill_start: list[str]) -> str:
    title = "Core"
    if skill_max:
        title += f" — max {'>'.join(skill_max)}"
        if skill_start:
            title += f" (start {'-'.join(skill_start)})"
    return title


def make_item_set(champion_id: int, title: str, item_build: ItemBuild,
                  core_title: str = "Core") -> dict:
    blocks = []
    if item_build.starter_ids:
        blocks.append(_item_block("Starters", item_build.starter_ids))
    if item_build.core_ids:
        blocks.append(_item_block(core_title, item_build.core_ids))
    if item_build.boots_ids:
        blocks.append(_item_block("Boots", item_build.boots_ids))
    if item_build.situational_ids:
        blocks.append(_item_block("Situational", item_build.situational_ids))
    return {
        "title": title,
        "type": "custom",
        "map": "any",
        "mode": "any",
        "sortrank": 0,
        "startedFrom": "blank",
        "associatedChampions": [champion_id],
        "associatedMaps": [],
        "preferredItemSlots": [],
        "blocks": blocks,
    }


def item_set_document(existing_doc: dict, champion_id: int, title: str,
                      item_build: ItemBuild, core_title: str = "Core") -> dict:
    doc = dict(existing_doc) if isinstance(existing_doc, dict) else {}
    kept = [s for s in (doc.get("itemSets") or [])
            if not str(s.get("title", "")).startswith(PAGE_PREFIX)]
    kept.append(make_item_set(champion_id, title, item_build, core_title))
    doc["itemSets"] = kept
    return doc


class BuildApplier:
    def __init__(self, lcu, provider, get_config: Callable[[], Config],
                 get_champion_name: Callable[[int], str]) -> None:
        self._lcu = lcu
        self._provider = provider
        self._get_config = get_config
        self._get_champion_name = get_champion_name

    async def apply(self, champion_id: int, role: str) -> None:
        cfg = self._get_config()
        if not (cfg.auto_runes or cfg.use_meta_spells or cfg.auto_items) or cfg.master_paused:
            return
        build = await self._provider.get_build(champion_id, role)
        if build is None:
            log.warning("No meta build available for %s", self._get_champion_name(champion_id))
            return
        if cfg.auto_runes:
            await self._apply_page(build, champion_id)
        if cfg.use_meta_spells:
            await self._apply_spells(build, cfg)
        if cfg.auto_items:
            await self._apply_item_set(build, champion_id)

    async def _apply_page(self, build: Build, champion_id: int) -> None:
        payload = {
            "name": f"{PAGE_PREFIX} {self._get_champion_name(champion_id)}",
            "primaryStyleId": build.primary_style_id,
            "subStyleId": build.sub_style_id,
            "selectedPerkIds": build.perk_ids,
            "current": True,
        }
        try:
            pages = await self._lcu.get("/lol-perks/v1/pages") or []
            existing = next((p for p in pages
                             if p.get("name", "").startswith(PAGE_PREFIX)
                             and p.get("isEditable", True)), None)
            if existing:
                await self._lcu.put(f"/lol-perks/v1/pages/{existing['id']}", payload)
                page_id = existing["id"]
            else:
                created = await self._lcu.post("/lol-perks/v1/pages", payload)
                page_id = created["id"]
            await self._lcu.put("/lol-perks/v1/currentpage", page_id)
            log.info("Applied rune page %r", payload["name"])
        except (LCUError, KeyError, TypeError) as exc:
            log.warning("Applying rune page failed: %s", exc)

    async def _apply_spells(self, build: Build, cfg: Config) -> None:
        s1, s2 = ordered_spells(build.spell_ids[0], build.spell_ids[1], cfg.flash_on_f)
        try:
            await self._lcu.patch("/lol-champ-select/v1/session/my-selection",
                                  {"spell1Id": s1, "spell2Id": s2})
            log.info("Applied meta summoner spells")
        except LCUError as exc:
            log.warning("Applying meta spells failed: %s", exc)

    async def suggest_counters(self, champion_id: int, role: str) -> None:
        """Log the strongest counters to the intended pick (informational only).

        Called during champ-select planning; also warms the provider's fetch
        cache so the lock-in apply usually needs no second request.
        """
        try:
            build = await self._provider.get_build(champion_id, role)
            if build is None or not build.counter_ids:
                return
            parts = [f"{self._get_champion_name(cid)} ({winrate:.0%})"
                     for cid, winrate in build.counter_ids]
            log.info("Counters to %s worth banning: %s",
                     self._get_champion_name(champion_id), ", ".join(parts))
        except Exception as exc:
            log.warning("Counter suggestion failed: %s", exc)

    async def _apply_item_set(self, build: Build, champion_id: int) -> None:
        if build.items is None or build.items.is_empty():
            return
        title = f"{PAGE_PREFIX} {self._get_champion_name(champion_id)}"
        try:
            summoner = await self._lcu.get("/lol-summoner/v1/current-summoner") or {}
            summoner_id = summoner.get("summonerId")
            if not summoner_id:
                return
            path = f"/lol-item-sets/v1/item-sets/{summoner_id}/sets"
            document = await self._lcu.get(path)
            if not isinstance(document, dict):
                # Unexpected shape — don't risk overwriting the user's own sets.
                log.warning("Item set doc had unexpected shape; skipping")
                return
            core_title = core_block_title(build.skill_max, build.skill_start)
            await self._lcu.put(path, item_set_document(document, champion_id, title,
                                                        build.items, core_title))
            log.info("Applied item set %r", title)
        except (LCUError, KeyError, TypeError) as exc:
            log.warning("Applying item set failed: %s", exc)
