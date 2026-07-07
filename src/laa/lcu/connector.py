from __future__ import annotations

import json

from . import events


class LCUError(Exception):
    """Any failure talking to the League client."""


def _parse_message(raw: str | bytes) -> events.LCUEvent | None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, list) or len(msg) < 3 or msg[0] != 8 or not isinstance(msg[2], dict):
        return None
    uri = msg[2].get("uri")
    data = msg[2].get("data")
    if uri == "/lol-gameflow/v1/gameflow-phase" and isinstance(data, str):
        return events.GameflowPhase(phase=data)
    if uri == "/lol-matchmaking/v1/ready-check" and isinstance(data, dict):
        return events.ReadyCheckUpdate(
            state=data.get("state", ""), player_response=data.get("playerResponse", "")
        )
    if uri == "/lol-champ-select/v1/session" and isinstance(data, dict):
        return events.ChampSelectUpdate(session=data)
    return None
