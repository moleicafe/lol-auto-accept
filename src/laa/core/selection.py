from __future__ import annotations

from typing import Any

from laa.config import FLASH_ID

Session = dict[str, Any]


def flat_actions(session: Session) -> list[dict]:
    return [a for group in session.get("actions", []) for a in group]


def my_active_actions(session: Session) -> list[dict]:
    cell = session.get("localPlayerCellId")
    return [a for a in flat_actions(session)
            if a.get("actorCellId") == cell and a.get("isInProgress") and not a.get("completed")]


def banned_ids(session: Session) -> set[int]:
    return {a["championId"] for a in flat_actions(session)
            if a.get("type") == "ban" and a.get("completed") and a.get("championId")}


def picked_ids(session: Session) -> set[int]:
    return {a["championId"] for a in flat_actions(session)
            if a.get("type") == "pick" and a.get("completed") and a.get("championId")}


def choose_ban(ban_list: list[int], session: Session, bannable: set[int]) -> int | None:
    gone = banned_ids(session)
    for cid in ban_list:
        if cid in bannable and cid not in gone:
            return cid
    return None


def choose_pick(pick_list: list[int], session: Session, pickable: set[int]) -> int | None:
    unavailable = banned_ids(session) | picked_ids(session)
    for cid in pick_list:
        if cid in pickable and cid not in unavailable:
            return cid
    return None


def assigned_position(session: Session) -> str:
    cell = session.get("localPlayerCellId")
    for member in session.get("myTeam", []):
        if member.get("cellId") == cell:
            return member.get("assignedPosition") or ""
    return ""


def my_completed_pick(session: Session) -> int | None:
    cell = session.get("localPlayerCellId")
    for a in flat_actions(session):
        if (a.get("type") == "pick" and a.get("actorCellId") == cell
                and a.get("completed") and a.get("championId")):
            return a["championId"]
    return None


def ordered_spells(spell1: int, spell2: int, flash_on_f: bool) -> tuple[int, int]:
    ids = (spell1, spell2)
    if FLASH_ID not in ids:
        return ids
    other = ids[0] if ids[1] == FLASH_ID else ids[1]
    return (other, FLASH_ID) if flash_on_f else (FLASH_ID, other)


def pick_time_left_s(session: Session) -> float | None:
    timer = session.get("timer") or {}
    if timer.get("isInfinite") or timer.get("phase") != "BAN_PICK":
        return None
    ms = timer.get("adjustedTimeLeftInPhase")
    if not isinstance(ms, (int, float)):
        return None
    return max(0.0, ms / 1000.0)


def lock_target(session: Session, pick_list: list[int], pickable: set[int]) -> int | None:
    for a in my_active_actions(session):
        if a.get("type") == "pick":
            hovered = a.get("championId") or 0
            return hovered if hovered > 0 else choose_pick(pick_list, session, pickable)
    return None
