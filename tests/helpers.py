"""Shared fixtures: synthetic champ-select sessions and a fake LCU."""
from __future__ import annotations

from typing import Any


def action(aid: int, cell: int, type_: str, champion_id: int = 0,
           completed: bool = False, in_progress: bool = False) -> dict:
    return {"id": aid, "actorCellId": cell, "type": type_, "championId": champion_id,
            "completed": completed, "isInProgress": in_progress}


def make_session(cell: int = 0, actions: list[list[dict]] | None = None,
                 position: str = "middle", time_left_ms: int | None = None,
                 timer_infinite: bool = False, phase: str = "BAN_PICK") -> dict:
    timer: dict = {"phase": phase}
    if timer_infinite:
        timer["isInfinite"] = True
    if time_left_ms is not None:
        timer["adjustedTimeLeftInPhase"] = time_left_ms
    return {
        "localPlayerCellId": cell,
        "actions": actions or [],
        "myTeam": [{"cellId": cell, "championId": 0, "assignedPosition": position}],
        "theirTeam": [],
        "timer": timer,
    }


class FakeLCU:
    """Records calls; returns canned responses keyed by (METHOD, path)."""

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, Any]] = []

    async def _do(self, method: str, path: str, body: Any = None) -> Any:
        self.calls.append((method, path, body))
        return self.responses.get((method, path))

    async def get(self, path):
        return await self._do("GET", path)

    async def post(self, path, json_body=None):
        return await self._do("POST", path, json_body)

    async def patch(self, path, json_body=None):
        return await self._do("PATCH", path, json_body)

    async def put(self, path, json_body=None):
        return await self._do("PUT", path, json_body)

    async def delete(self, path):
        return await self._do("DELETE", path)

    def sent(self, method: str, path_prefix: str) -> list[tuple[str, str, Any]]:
        return [c for c in self.calls if c[0] == method and c[1].startswith(path_prefix)]
