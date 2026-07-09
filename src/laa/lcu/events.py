from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Connected:
    pass


@dataclass(frozen=True)
class Disconnected:
    pass


@dataclass(frozen=True)
class GameflowPhase:
    phase: str  # "None", "Lobby", "Matchmaking", "ReadyCheck", "ChampSelect", "InProgress", ...


@dataclass(frozen=True)
class ReadyCheckUpdate:
    state: str            # "InProgress", "EveryoneReady", ...
    player_response: str  # "None", "Accepted", "Declined"


@dataclass(frozen=True)
class ChampSelectUpdate:
    session: dict[str, Any]


LCUEvent = Connected | Disconnected | GameflowPhase | ReadyCheckUpdate | ChampSelectUpdate
