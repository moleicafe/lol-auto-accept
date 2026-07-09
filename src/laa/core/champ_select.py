from __future__ import annotations

import asyncio
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
        task = getattr(self, "_safety_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._safety_task: asyncio.Task | None = None
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
        self._arm_safety_lock(cfg, session)

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

    def _cancel_safety(self) -> None:
        if self._safety_task is not None and not self._safety_task.done():
            self._safety_task.cancel()
        self._safety_task = None

    def _arm_safety_lock(self, cfg: Config, session: dict) -> None:
        if cfg.master_paused or not cfg.safety_lock or cfg.instalock:
            self._cancel_safety()
            return
        pick = next((a for a in selection.my_active_actions(session)
                     if a.get("type") == "pick"), None)
        time_left = selection.pick_time_left_s(session)
        if pick is None or time_left is None:
            self._cancel_safety()
            return
        delay = max(0.0, time_left - cfg.safety_lock_buffer_s)
        self._cancel_safety()
        self._safety_task = asyncio.create_task(
            self._safety_lock_after(delay, pick["id"]))

    async def _safety_lock_after(self, delay: float, action_id: int) -> None:
        await asyncio.sleep(delay)  # CancelledError propagates cleanly on reset/re-arm
        try:
            await self._fire_safety_lock(action_id)
        except Exception:
            log.exception("Safety-lock task error")

    async def _fire_safety_lock(self, action_id: int) -> None:
        cfg = self._get_config()
        if cfg.master_paused or not cfg.safety_lock or cfg.instalock:
            return
        try:
            session = await self._lcu.get("/lol-champ-select/v1/session")
        except LCUError as exc:
            log.warning("Safety lock: session read failed: %s", exc)
            return
        if not isinstance(session, dict):
            return
        action = next((a for a in selection.flat_actions(session)
                       if a.get("id") == action_id), None)
        if action is None or action.get("completed") or not action.get("isInProgress"):
            return  # already locked, dodged, or phase changed
        if not self._pickable:
            try:
                self._pickable = set(await self._lcu.get(
                    "/lol-champ-select/v1/pickable-champion-ids") or [])
            except LCUError as exc:
                log.warning("Safety lock: pickable fetch failed: %s", exc)
                return
        cid = selection.lock_target(session, cfg.pick_ids, self._pickable)
        if cid is None:
            log.info("Safety lock: nothing to lock")
            return
        try:
            await self._lcu.patch(f"/lol-champ-select/v1/session/actions/{action_id}",
                                  {"championId": cid, "completed": True})
            self._acted[action_id] = (cid, True)
            log.info("Safety-locked champion %s", cid)
        except LCUError as exc:
            log.warning("Safety lock failed: %s", exc)
