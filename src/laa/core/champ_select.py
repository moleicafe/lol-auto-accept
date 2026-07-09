from __future__ import annotations

import logging
from typing import Awaitable, Callable

from laa.config import Config
from laa.core import selection
from laa.lcu.connector import LCUError

log = logging.getLogger(__name__)

OnLocked = Callable[[int, str], Awaitable[None]]


class ChampSelectAutomation:
    def __init__(self, lcu, get_config: Callable[[], Config],
                 on_locked: OnLocked | None = None) -> None:
        self._lcu = lcu
        self._get_config = get_config
        self._on_locked = on_locked
        self.reset()

    def reset(self) -> None:
        self._spells_done = False
        self._chat_done = False
        self._locked_notified = False
        self._acted: dict[int, tuple[int, bool]] = {}  # action id -> (championId, completed)
        self._pickable: set[int] | None = None
        self._bannable: set[int] | None = None

    async def on_session(self, session: dict) -> None:
        cfg = self._get_config()
        if cfg.master_paused:
            return
        if cfg.set_spells and not self._spells_done:
            await self._apply_spells(cfg)
        if cfg.lobby_message and not self._chat_done:
            await self._send_chat(cfg.lobby_message)
        await self._handle_actions(cfg, session)
        await self._notify_lock(session)

    async def _apply_spells(self, cfg: Config) -> None:
        s1, s2 = selection.ordered_spells(cfg.spell1_id, cfg.spell2_id, cfg.flash_on_f)
        try:
            await self._lcu.patch("/lol-champ-select/v1/session/my-selection",
                                  {"spell1Id": s1, "spell2Id": s2})
            self._spells_done = True
            log.info("Summoner spells set")
        except LCUError as exc:
            log.warning("Setting spells failed: %s", exc)

    async def _send_chat(self, message: str) -> None:
        try:
            convos = await self._lcu.get("/lol-chat/v1/conversations") or []
            convo = next((c for c in convos if c.get("type") == "championSelect"), None)
            if convo is None:
                return  # chat room not up yet; retry on next session update
            await self._lcu.post(f"/lol-chat/v1/conversations/{convo['id']}/messages",
                                 {"body": message, "type": "chat"})
            self._chat_done = True
            log.info("Lobby message sent")
        except LCUError as exc:
            log.warning("Lobby chat failed: %s", exc)

    async def _handle_actions(self, cfg: Config, session: dict) -> None:
        for act in selection.my_active_actions(session):
            try:
                if act.get("type") == "ban" and cfg.ban_ids:
                    await self._do_ban(cfg, session, act)
                elif act.get("type") == "pick" and cfg.pick_ids:
                    await self._do_pick(cfg, session, act)
            except LCUError as exc:
                log.warning("Champ select action failed: %s", exc)

    async def _do_ban(self, cfg: Config, session: dict, act: dict) -> None:
        if not self._bannable:
            self._bannable = set(await self._lcu.get(
                "/lol-champ-select/v1/bannable-champion-ids") or [])
        cid = selection.choose_ban(cfg.ban_ids, session, self._bannable)
        if cid is None or self._acted.get(act["id"]) == (cid, True):
            return
        await self._lcu.patch(f"/lol-champ-select/v1/session/actions/{act['id']}",
                              {"championId": cid, "completed": True})
        self._acted[act["id"]] = (cid, True)
        log.info("Banned champion %s", cid)

    async def _do_pick(self, cfg: Config, session: dict, act: dict) -> None:
        if not self._pickable:
            self._pickable = set(await self._lcu.get(
                "/lol-champ-select/v1/pickable-champion-ids") or [])
        cid = selection.choose_pick(cfg.pick_ids, session, self._pickable)
        if cid is None or self._acted.get(act["id"]) == (cid, cfg.instalock):
            return
        body: dict = {"championId": cid}
        if cfg.instalock:
            body["completed"] = True
        await self._lcu.patch(f"/lol-champ-select/v1/session/actions/{act['id']}", body)
        self._acted[act["id"]] = (cid, cfg.instalock)
        log.info("%s champion %s", "Locked" if cfg.instalock else "Hovered", cid)

    async def _notify_lock(self, session: dict) -> None:
        if self._locked_notified or self._on_locked is None:
            return
        cid = selection.my_completed_pick(session)
        if cid is None:
            return
        self._locked_notified = True
        await self._on_locked(cid, selection.assigned_position(session))
