# League Auto Accept (Python) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild LeagueAutoAccept as a Python desktop app: LCU automation (auto-accept, pick/ban, instalock, spells, lobby chat) plus auto meta-rune import, with a PySide6 GUI + system tray, packaged as a standalone exe.

**Architecture:** Three layers with one-way event flow: an asyncio **LCU connector** (process discovery → httpx + websocket) emits typed events to an **automation engine** (pure-logic state machine per gameflow phase), observed by a **PySide6 GUI** via Qt signals. The connector/engine run on a background thread; the GUI owns the main thread. Config is a JSON-backed dataclass swapped atomically between threads.

**Tech Stack:** Python 3.12+, PySide6, httpx, websockets (≥14), psutil. Dev: pytest, pytest-asyncio, pytest-qt, aiohttp (fake LCU server), PyInstaller, Pillow (icon generation only).

**Spec:** `docs/superpowers/specs/2026-07-08-league-auto-accept-design.md`

## Global Constraints

- Windows-only; Python **3.12+**; package lives in `src/laa/`; tests in `tests/`.
- Runtime dependencies limited to: `PySide6>=6.7`, `httpx>=0.27`, `websockets>=14`, `psutil>=5.9`.
- Config JSON at `%APPDATA%\LeagueAutoAccept\config.json`; logs at `%APPDATA%\LeagueAutoAccept\laa.log`.
- Rune fetch failures must **never** block or delay picking — silent degrade, log only.
- Rune pages created by the app are named `LAA: <Champion>`; never modify other pages.
- Every automation individually toggleable; master pause overrides all.
- All tests run with `.venv\Scripts\python -m pytest -q` from the project root; commit after every task.
- The engine layer (`laa/core/`, `laa/runes/`) must not import Qt.

---

### Task 1: Project scaffold + config module

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/laa/__init__.py`, `src/laa/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `laa.config.Config` (dataclass, fields below), `load(path: Path | None = None) -> Config`, `save(cfg: Config, path: Path | None = None) -> None`, `config_dir() -> Path`, `config_path() -> Path`, constant `FLASH_ID = 4`. Later tasks read config via a `get_config: Callable[[], Config]` closure.

- [ ] **Step 1: Create venv and project skeleton**

Create `pyproject.toml`:

```toml
[project]
name = "laa"
version = "1.0.0"
description = "League Auto Accept - LCU automation with GUI"
requires-python = ">=3.12"
dependencies = [
  "PySide6>=6.7",
  "httpx>=0.27",
  "websockets>=14",
  "psutil>=5.9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "pytest-qt>=4.4",
  "aiohttp>=3.10",
  "pyinstaller>=6.10",
  "pillow>=10",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Create `.gitignore`:

```
.venv/
__pycache__/
*.pyc
build/
dist/
*.spec
```

Create empty `src/laa/__init__.py`. Then:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Expected: install succeeds (PySide6 wheel is large, ~1–2 min).

- [ ] **Step 2: Write failing config tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

from laa.config import Config, load, save


def test_defaults_when_file_missing(tmp_path: Path):
    cfg = load(tmp_path / "nope.json")
    assert cfg.auto_accept is True
    assert cfg.pick_ids == []
    assert cfg.instalock is False
    assert cfg.auto_runes is True


def test_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Config(pick_ids=[103, 1], ban_ids=[157], lobby_message="glhf", accept_delay_s=2.0)
    save(cfg, path)
    loaded = load(path)
    assert loaded == cfg


def test_corrupt_file_returns_defaults(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{not json!!", encoding="utf-8")
    assert load(path) == Config()


def test_unknown_keys_ignored(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text('{"auto_accept": false, "some_future_key": 1}', encoding="utf-8")
    cfg = load(path)
    assert cfg.auto_accept is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.config'`

- [ ] **Step 4: Implement config module**

Create `src/laa/config.py`:

```python
from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FLASH_ID = 4


@dataclass
class Config:
    schema_version: int = SCHEMA_VERSION
    master_paused: bool = False
    # queue
    auto_accept: bool = True
    accept_delay_s: float = 0.0
    # champ select
    pick_ids: list[int] = field(default_factory=list)
    ban_ids: list[int] = field(default_factory=list)
    instalock: bool = False
    set_spells: bool = False
    spell1_id: int = 4
    spell2_id: int = 14
    flash_on_f: bool = True
    lobby_message: str = ""
    # runes
    auto_runes: bool = True
    use_meta_spells: bool = False
    # ui
    tray_hint_shown: bool = False


def config_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "LeagueAutoAccept"


def config_path() -> Path:
    return config_dir() / "config.json"


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in dataclasses.fields(Config)}
        return Config(**{k: v for k, v in raw.items() if k in known})
    except FileNotFoundError:
        return Config()
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Corrupt config at %s (%s); using defaults", path, exc)
        return Config()


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(cfg), indent=2), encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 4 passed

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: project scaffold and config module"
```

---

### Task 2: LCU discovery, event types, websocket message parsing

**Files:**
- Create: `src/laa/lcu/__init__.py`, `src/laa/lcu/discovery.py`, `src/laa/lcu/events.py`
- Create: `src/laa/lcu/connector.py` (only `LCUError` + `_parse_message` in this task; runtime added in Task 3)
- Test: `tests/test_discovery.py`, `tests/test_parse_message.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `laa.lcu.discovery`: `LCUCredentials(port: int, token: str)` (frozen dataclass), `parse_cmdline(cmdline: str) -> LCUCredentials | None`, `find_credentials() -> LCUCredentials | None`, `PROCESS_NAME = "LeagueClientUx.exe"`
  - `laa.lcu.events`: frozen dataclasses `Connected()`, `Disconnected()`, `GameflowPhase(phase: str)`, `ReadyCheckUpdate(state: str, player_response: str)`, `ChampSelectUpdate(session: dict)`; type alias `LCUEvent`
  - `laa.lcu.connector`: `LCUError(Exception)`, `_parse_message(raw: str | bytes) -> LCUEvent | None`

- [ ] **Step 1: Write failing tests**

Create `tests/test_discovery.py`:

```python
from laa.lcu.discovery import LCUCredentials, parse_cmdline

CMDLINE = (
    '"C:/Riot Games/League of Legends/LeagueClientUx.exe" '
    '--riotclient-auth-token=xyz --app-port=52345 '
    '--remoting-auth-token=AbC-123_dEf --app-pid=1234'
)


def test_parse_cmdline_extracts_port_and_token():
    creds = parse_cmdline(CMDLINE)
    assert creds == LCUCredentials(port=52345, token="AbC-123_dEf")


def test_parse_cmdline_missing_flags_returns_none():
    assert parse_cmdline("LeagueClientUx.exe --app-port=1") is None
    assert parse_cmdline("") is None
```

Create `tests/test_parse_message.py`:

```python
import json

from laa.lcu import events
from laa.lcu.connector import _parse_message


def wrap(uri, data):
    return json.dumps([8, "OnJsonApiEvent", {"uri": uri, "eventType": "Update", "data": data}])


def test_gameflow_phase():
    ev = _parse_message(wrap("/lol-gameflow/v1/gameflow-phase", "ReadyCheck"))
    assert ev == events.GameflowPhase(phase="ReadyCheck")


def test_ready_check():
    ev = _parse_message(wrap("/lol-matchmaking/v1/ready-check", {"state": "InProgress", "playerResponse": "None"}))
    assert ev == events.ReadyCheckUpdate(state="InProgress", player_response="None")


def test_champ_select():
    ev = _parse_message(wrap("/lol-champ-select/v1/session", {"localPlayerCellId": 0}))
    assert ev == events.ChampSelectUpdate(session={"localPlayerCellId": 0})


def test_irrelevant_uri_returns_none():
    assert _parse_message(wrap("/lol-lobby/v2/lobby", {})) is None


def test_garbage_returns_none():
    assert _parse_message("not json") is None
    assert _parse_message(json.dumps([5, "OnJsonApiEvent"])) is None
    assert _parse_message(json.dumps({"uri": "x"})) is None


def test_ready_check_delete_event_with_null_data_returns_none():
    assert _parse_message(wrap("/lol-matchmaking/v1/ready-check", None)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_discovery.py tests/test_parse_message.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.lcu'`

- [ ] **Step 3: Implement**

Create empty `src/laa/lcu/__init__.py`.

Create `src/laa/lcu/discovery.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

import psutil

PROCESS_NAME = "LeagueClientUx.exe"
_PORT_RE = re.compile(r"--app-port=(\d+)")
_TOKEN_RE = re.compile(r"--remoting-auth-token=([\w-]+)")


@dataclass(frozen=True)
class LCUCredentials:
    port: int
    token: str


def parse_cmdline(cmdline: str) -> LCUCredentials | None:
    port_m = _PORT_RE.search(cmdline)
    token_m = _TOKEN_RE.search(cmdline)
    if not port_m or not token_m:
        return None
    return LCUCredentials(port=int(port_m.group(1)), token=token_m.group(1))


def find_credentials() -> LCUCredentials | None:
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] == PROCESS_NAME and proc.info["cmdline"]:
                creds = parse_cmdline(" ".join(proc.info["cmdline"]))
                if creds:
                    return creds
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None
```

Create `src/laa/lcu/events.py`:

```python
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
```

Create `src/laa/lcu/connector.py` (parsing part only; Task 3 appends the connector class):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass (Task 1's 4 + these 8)

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: LCU discovery, typed events, websocket message parsing"
```

---

### Task 3: LCU connector runtime (discovery loop, websocket pump, request helpers)

**Files:**
- Modify: `src/laa/lcu/connector.py` (append connector class)
- Test: `tests/test_connector.py`

**Interfaces:**
- Consumes: `LCUCredentials`, `find_credentials`, `events`, `_parse_message`, `LCUError` (Task 2)
- Produces: `laa.lcu.connector.LCUConnector` with:
  - `__init__(self, on_event: Callable[[LCUEvent], Awaitable[None]], find_creds=find_credentials, poll_interval: float = 2.0, secure: bool = True)`
  - `async run(self) -> None` — runs forever (discover → connect → pump → on loss, emit `Disconnected` and retry)
  - `async get(path) / post(path, json_body=None) / patch(...) / put(...) / delete(path) -> Any` — raise `LCUError` when disconnected or on HTTP ≥400. **All later tasks call the LCU exclusively through these five methods.**
  - Emits `Connected()` once the websocket subscription is live; parsed events thereafter.
  - `secure=False` uses `http://`/`ws://` (tests only).

- [ ] **Step 1: Write failing integration test with a fake LCU server**

Create `tests/test_connector.py`:

```python
import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from laa.lcu import events
from laa.lcu.connector import LCUConnector, LCUError
from laa.lcu.discovery import LCUCredentials


async def make_fake_lcu():
    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        msg = await ws.receive_json()
        assert msg == [5, "OnJsonApiEvent"]
        await ws.send_json(
            [8, "OnJsonApiEvent",
             {"uri": "/lol-gameflow/v1/gameflow-phase", "eventType": "Update", "data": "Lobby"}]
        )
        async for _ in ws:  # stay open until client/server closes
            pass
        return ws

    async def phase(request):
        return web.json_response("Lobby")

    app = web.Application()
    app.router.add_get("/", ws_handler)
    app.router.add_get("/lol-gameflow/v1/gameflow-phase", phase)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    return server


async def test_connect_receive_event_request_and_disconnect():
    server = await make_fake_lcu()
    received: list = []
    connected = asyncio.Event()
    disconnected = asyncio.Event()

    async def on_event(ev):
        received.append(ev)
        if isinstance(ev, events.Connected):
            connected.set()
        if isinstance(ev, events.Disconnected):
            disconnected.set()

    creds = LCUCredentials(port=server.port, token="testtoken")
    conn = LCUConnector(on_event, find_creds=lambda: creds, poll_interval=0.05, secure=False)
    task = asyncio.create_task(conn.run())
    try:
        await asyncio.wait_for(connected.wait(), 5)
        # request helper works while connected
        assert await conn.get("/lol-gameflow/v1/gameflow-phase") == "Lobby"
        # parsed websocket event arrives
        await asyncio.wait_for(_wait_for_phase(received), 5)
        # server death -> Disconnected
        await server.close()
        await asyncio.wait_for(disconnected.wait(), 5)
    finally:
        task.cancel()

    with pytest.raises(LCUError):
        await conn.get("/anything")


async def _wait_for_phase(received):
    while not any(isinstance(e, events.GameflowPhase) and e.phase == "Lobby" for e in received):
        await asyncio.sleep(0.01)


async def test_request_while_disconnected_raises():
    conn = LCUConnector(lambda e: None, find_creds=lambda: None, secure=False)
    with pytest.raises(LCUError):
        await conn.get("/lol-summoner/v1/current-summoner")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest -q tests/test_connector.py`
Expected: FAIL — `ImportError: cannot import name 'LCUConnector'`

- [ ] **Step 3: Implement the connector class**

Append to `src/laa/lcu/connector.py` (add imports at top of file):

```python
import asyncio
import base64
import logging
import ssl
from typing import Any, Awaitable, Callable

import httpx
import websockets

from .discovery import LCUCredentials, find_credentials

log = logging.getLogger(__name__)

EventCallback = Callable[["events.LCUEvent"], Awaitable[None] | None]


class LCUConnector:
    """Finds the League client, pumps websocket events, exposes request helpers."""

    def __init__(
        self,
        on_event: EventCallback,
        find_creds: Callable[[], LCUCredentials | None] = find_credentials,
        poll_interval: float = 2.0,
        secure: bool = True,
    ) -> None:
        self._on_event = on_event
        self._find_creds = find_creds
        self._poll_interval = poll_interval
        self._secure = secure
        self._client: httpx.AsyncClient | None = None

    async def run(self) -> None:
        while True:
            creds = self._find_creds()
            if creds is None:
                await asyncio.sleep(self._poll_interval)
                continue
            try:
                await self._session(creds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.info("LCU connection lost: %s", exc)
            await self._emit(events.Disconnected())
            await asyncio.sleep(self._poll_interval)

    async def _emit(self, event: "events.LCUEvent") -> None:
        result = self._on_event(event)
        if asyncio.iscoroutine(result):
            await result

    async def _session(self, creds: LCUCredentials) -> None:
        scheme = "https" if self._secure else "http"
        async with httpx.AsyncClient(
            base_url=f"{scheme}://127.0.0.1:{creds.port}",
            auth=("riot", creds.token),
            verify=False,
            timeout=10.0,
        ) as client:
            self._client = client
            try:
                await self._pump(creds)
            finally:
                self._client = None

    async def _pump(self, creds: LCUCredentials) -> None:
        ws_scheme = "wss" if self._secure else "ws"
        kwargs: dict[str, Any] = {"max_size": 2**24}
        if self._secure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ctx
        basic = base64.b64encode(f"riot:{creds.token}".encode()).decode()
        kwargs["additional_headers"] = {"Authorization": f"Basic {basic}"}
        async with websockets.connect(f"{ws_scheme}://127.0.0.1:{creds.port}/", **kwargs) as ws:
            await ws.send(json.dumps([5, "OnJsonApiEvent"]))
            await self._emit(events.Connected())
            async for raw in ws:
                event = _parse_message(raw)
                if event is not None:
                    await self._emit(event)

    async def request(self, method: str, path: str, json_body: Any = None) -> Any:
        if self._client is None:
            raise LCUError("not connected to League client")
        try:
            resp = await self._client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise LCUError(f"{method} {path}: {exc}") from exc
        if resp.status_code >= 400:
            raise LCUError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    async def get(self, path: str) -> Any:
        return await self.request("GET", path)

    async def post(self, path: str, json_body: Any = None) -> Any:
        return await self.request("POST", path, json_body)

    async def patch(self, path: str, json_body: Any = None) -> Any:
        return await self.request("PATCH", path, json_body)

    async def put(self, path: str, json_body: Any = None) -> Any:
        return await self.request("PUT", path, json_body)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass. If `websockets.connect` rejects `additional_headers`, the installed websockets is <14 — fix the venv (`pip install "websockets>=14"`), not the code.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: LCU connector runtime with reconnect and request helpers"
```

---

### Task 4: Pure selection logic (pick/ban choice, positions, spell ordering)

**Files:**
- Create: `src/laa/core/__init__.py`, `src/laa/core/selection.py`
- Test: `tests/test_selection.py`, `tests/helpers.py`

**Interfaces:**
- Consumes: `laa.config.FLASH_ID`
- Produces (`laa.core.selection`, all pure functions over the LCU champ-select session dict):
  - `flat_actions(session) -> list[dict]`
  - `my_active_actions(session) -> list[dict]` — local player's `isInProgress and not completed` actions
  - `banned_ids(session) -> set[int]`, `picked_ids(session) -> set[int]` — from completed actions
  - `choose_ban(ban_list: list[int], session, bannable: set[int]) -> int | None`
  - `choose_pick(pick_list: list[int], session, pickable: set[int]) -> int | None`
  - `assigned_position(session) -> str` — e.g. `"middle"`, `""` when unassigned
  - `my_completed_pick(session) -> int | None`
  - `ordered_spells(spell1: int, spell2: int, flash_on_f: bool) -> tuple[int, int]`
- Test helper `tests/helpers.py`: `make_session(...)` and `FakeLCU` used by Tasks 5, 6, 8, 9.

- [ ] **Step 1: Write the shared test helpers**

Create `tests/helpers.py`:

```python
"""Shared fixtures: synthetic champ-select sessions and a fake LCU."""
from __future__ import annotations

from typing import Any


def action(aid: int, cell: int, type_: str, champion_id: int = 0,
           completed: bool = False, in_progress: bool = False) -> dict:
    return {"id": aid, "actorCellId": cell, "type": type_, "championId": champion_id,
            "completed": completed, "isInProgress": in_progress}


def make_session(cell: int = 0, actions: list[list[dict]] | None = None,
                 position: str = "middle") -> dict:
    return {
        "localPlayerCellId": cell,
        "actions": actions or [],
        "myTeam": [{"cellId": cell, "championId": 0, "assignedPosition": position}],
        "theirTeam": [],
        "timer": {"phase": "BAN_PICK"},
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
```

- [ ] **Step 2: Write failing selection tests**

Create `tests/test_selection.py`:

```python
from laa.core.selection import (assigned_position, choose_ban, choose_pick,
                                my_active_actions, my_completed_pick, ordered_spells)
from tests.helpers import action, make_session


def test_my_active_actions_filters_to_local_in_progress():
    s = make_session(cell=2, actions=[
        [action(1, 0, "ban", in_progress=True)],
        [action(2, 2, "ban", in_progress=True), action(3, 2, "pick")],
        [action(4, 2, "pick", completed=True, in_progress=True)],
    ])
    assert [a["id"] for a in my_active_actions(s)] == [2]


def test_choose_ban_skips_unbannable_and_already_banned():
    s = make_session(actions=[[action(1, 3, "ban", champion_id=157, completed=True)]])
    assert choose_ban([157, 238, 555], s, bannable={238, 555}) == 238


def test_choose_ban_none_when_list_exhausted():
    assert choose_ban([157], make_session(), bannable=set()) is None


def test_choose_pick_skips_banned_taken_unowned():
    s = make_session(actions=[
        [action(1, 3, "ban", champion_id=103, completed=True)],   # Ahri banned
        [action(2, 4, "pick", champion_id=1, completed=True)],    # Annie taken
    ])
    # 103 banned, 1 taken, 61 unowned (not pickable) -> 245
    assert choose_pick([103, 1, 61, 245], s, pickable={103, 1, 245}) == 245


def test_choose_pick_empty_list_returns_none():
    assert choose_pick([], make_session(), pickable={1}) is None


def test_assigned_position():
    assert assigned_position(make_session(position="jungle")) == "jungle"
    assert assigned_position(make_session(position="")) == ""


def test_my_completed_pick():
    s = make_session(actions=[[action(1, 0, "pick", champion_id=103, completed=True)]])
    assert my_completed_pick(s) == 103
    assert my_completed_pick(make_session()) is None


def test_ordered_spells_flash_preference():
    assert ordered_spells(4, 14, flash_on_f=True) == (14, 4)
    assert ordered_spells(4, 14, flash_on_f=False) == (4, 14)
    assert ordered_spells(14, 4, flash_on_f=False) == (4, 14)
    assert ordered_spells(12, 14, flash_on_f=True) == (12, 14)  # no flash: unchanged
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_selection.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.core'`

- [ ] **Step 4: Implement selection module**

Create empty `src/laa/core/__init__.py` and `src/laa/core/selection.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: pure pick/ban selection logic and spell ordering"
```

---

### Task 5: Ready-check automation

**Files:**
- Create: `src/laa/core/ready_check.py`
- Test: `tests/test_ready_check.py`

**Interfaces:**
- Consumes: `LCUError` (Task 2), `ReadyCheckUpdate` (Task 2), `Config` via `get_config` closure (Task 1), `FakeLCU` (Task 4)
- Produces: `laa.core.ready_check.ReadyCheckAutomation`:
  - `__init__(self, lcu, get_config: Callable[[], Config])`
  - `reset() -> None` — call on gameflow phase change
  - `async on_update(self, update: ReadyCheckUpdate) -> None` — accepts at most once per ready check via `POST /lol-matchmaking/v1/ready-check/accept`, honoring `auto_accept`, `master_paused`, `accept_delay_s`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ready_check.py`:

```python
from laa.config import Config
from laa.core.ready_check import ReadyCheckAutomation
from laa.lcu.events import ReadyCheckUpdate
from tests.helpers import FakeLCU

ACCEPT = ("POST", "/lol-matchmaking/v1/ready-check/accept")
IN_PROGRESS = ReadyCheckUpdate(state="InProgress", player_response="None")


async def test_accepts_when_in_progress():
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config())
    await auto.on_update(IN_PROGRESS)
    assert [(c[0], c[1]) for c in lcu.calls] == [ACCEPT]


async def test_accepts_only_once_until_reset():
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config())
    await auto.on_update(IN_PROGRESS)
    await auto.on_update(IN_PROGRESS)
    assert len(lcu.calls) == 1
    auto.reset()
    await auto.on_update(IN_PROGRESS)
    assert len(lcu.calls) == 2


async def test_no_accept_when_disabled_or_paused():
    for cfg in (Config(auto_accept=False), Config(master_paused=True)):
        lcu = FakeLCU()
        await ReadyCheckAutomation(lcu, lambda c=cfg: c).on_update(IN_PROGRESS)
        assert lcu.calls == []


async def test_no_accept_when_already_responded():
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config())
    await auto.on_update(ReadyCheckUpdate(state="InProgress", player_response="Accepted"))
    assert lcu.calls == []


async def test_delay_is_honored(monkeypatch):
    import laa.core.ready_check as rc
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(rc.asyncio, "sleep", fake_sleep)
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config(accept_delay_s=3.0))
    await auto.on_update(IN_PROGRESS)
    assert slept == [3.0]
    assert len(lcu.calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_ready_check.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.core.ready_check'`

- [ ] **Step 3: Implement**

Create `src/laa/core/ready_check.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from laa.config import Config
from laa.lcu.connector import LCUError
from laa.lcu.events import ReadyCheckUpdate

log = logging.getLogger(__name__)

ACCEPT_PATH = "/lol-matchmaking/v1/ready-check/accept"


class ReadyCheckAutomation:
    def __init__(self, lcu, get_config: Callable[[], Config]) -> None:
        self._lcu = lcu
        self._get_config = get_config
        self._handled = False

    def reset(self) -> None:
        self._handled = False

    async def on_update(self, update: ReadyCheckUpdate) -> None:
        cfg = self._get_config()
        if self._handled or cfg.master_paused or not cfg.auto_accept:
            return
        if update.state != "InProgress" or update.player_response != "None":
            return
        self._handled = True
        if cfg.accept_delay_s > 0:
            await asyncio.sleep(cfg.accept_delay_s)
            cfg = self._get_config()  # user may have paused during the delay
            if cfg.master_paused or not cfg.auto_accept:
                self._handled = False
                return
        try:
            await self._lcu.post(ACCEPT_PATH)
            log.info("Ready check accepted")
        except LCUError as exc:
            log.warning("Accept failed: %s", exc)
            self._handled = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: auto-accept ready check with delay and idempotency"
```

---

### Task 6: Champ-select automation (actions, spells, chat, lock notification)

**Files:**
- Create: `src/laa/core/champ_select.py`
- Test: `tests/test_champ_select.py`

**Interfaces:**
- Consumes: selection functions (Task 4), `LCUError` (Task 2), `Config`/`get_config` (Task 1), `FakeLCU`/`make_session`/`action` (Task 4)
- Produces: `laa.core.champ_select.ChampSelectAutomation`:
  - `__init__(self, lcu, get_config, on_locked: Callable[[int, str], Awaitable[None]] | None = None)` — `on_locked(champion_id, assigned_position)` fires exactly once per champ select when the local pick completes
  - `reset() -> None`
  - `async on_session(self, session: dict) -> None` — idempotent per session update; each sub-feature guarded by its own config flag and try/except

LCU endpoints used: `GET /lol-champ-select/v1/pickable-champion-ids`, `GET /lol-champ-select/v1/bannable-champion-ids`, `PATCH /lol-champ-select/v1/session/actions/{id}`, `PATCH /lol-champ-select/v1/session/my-selection`, `GET /lol-chat/v1/conversations`, `POST /lol-chat/v1/conversations/{id}/messages`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_champ_select.py`:

```python
from laa.config import Config
from laa.core.champ_select import ChampSelectAutomation
from tests.helpers import FakeLCU, action, make_session

PICKABLE = ("GET", "/lol-champ-select/v1/pickable-champion-ids")
BANNABLE = ("GET", "/lol-champ-select/v1/bannable-champion-ids")
CONVOS = ("GET", "/lol-chat/v1/conversations")


def lcu_with(pickable=(103, 1, 245), bannable=(157, 238)):
    return FakeLCU({
        PICKABLE: list(pickable),
        BANNABLE: list(bannable),
        CONVOS: [{"id": "abc@champ-select.pvp.net", "type": "championSelect"}],
    })


def cfg(**kw):
    base = dict(pick_ids=[103, 245], ban_ids=[157, 238], set_spells=False,
                lobby_message="", instalock=False, auto_runes=False)
    base.update(kw)
    return Config(**base)


async def test_ban_declared_and_completed():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    await auto.on_session(make_session(actions=[[action(5, 0, "ban", in_progress=True)]]))
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5")
    assert patches == [("PATCH", "/lol-champ-select/v1/session/actions/5",
                        {"championId": 157, "completed": True})]


async def test_pick_hovers_without_instalock():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    await auto.on_session(make_session(actions=[[action(7, 0, "pick", in_progress=True)]]))
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")
    assert patches == [("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 103})]


async def test_pick_locks_with_instalock():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg(instalock=True))
    await auto.on_session(make_session(actions=[[action(7, 0, "pick", in_progress=True)]]))
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")
    assert patches[-1][2] == {"championId": 103, "completed": True}


async def test_pick_falls_back_when_first_choice_banned():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[
        [action(1, 3, "ban", champion_id=103, completed=True)],
        [action(7, 0, "pick", in_progress=True)],
    ])
    await auto.on_session(s)
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")
    assert patches == [("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 245})]


async def test_hover_not_repeated_for_same_champion():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[[action(7, 0, "pick", in_progress=True)]])
    await auto.on_session(s)
    await auto.on_session(s)
    assert len(lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")) == 1


async def test_spells_applied_once_with_flash_ordering():
    lcu = lcu_with()
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(set_spells=True, spell1_id=4, spell2_id=14, flash_on_f=True))
    await auto.on_session(make_session())
    await auto.on_session(make_session())
    sel = lcu.sent("PATCH", "/lol-champ-select/v1/session/my-selection")
    assert sel == [("PATCH", "/lol-champ-select/v1/session/my-selection",
                    {"spell1Id": 14, "spell2Id": 4})]


async def test_chat_message_sent_once():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg(lobby_message="glhf"))
    await auto.on_session(make_session())
    await auto.on_session(make_session())
    msgs = lcu.sent("POST", "/lol-chat/v1/conversations/abc@champ-select.pvp.net/messages")
    assert msgs == [("POST", "/lol-chat/v1/conversations/abc@champ-select.pvp.net/messages",
                     {"body": "glhf", "type": "chat"})]


async def test_on_locked_fires_once_with_position():
    lcu = lcu_with()
    locked: list = []

    async def on_locked(cid, pos):
        locked.append((cid, pos))

    auto = ChampSelectAutomation(lcu, lambda: cfg(), on_locked=on_locked)
    s = make_session(position="jungle",
                     actions=[[action(7, 0, "pick", champion_id=103, completed=True)]])
    await auto.on_session(s)
    await auto.on_session(s)
    assert locked == [(103, "jungle")]


async def test_paused_does_nothing():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg(master_paused=True, lobby_message="hi",
                                                  set_spells=True))
    await auto.on_session(make_session(actions=[[action(7, 0, "pick", in_progress=True)]]))
    assert lcu.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_champ_select.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.core.champ_select'`

- [ ] **Step 3: Implement**

Create `src/laa/core/champ_select.py`:

```python
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
        if self._bannable is None:
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
        if self._pickable is None:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: champ select automation - pick/ban, spells, chat, lock notify"
```

---

### Task 7: Rune provider (U.GG fetch + parse)

**Files:**
- Create: `src/laa/runes/__init__.py`, `src/laa/runes/provider.py`, `scripts/probe_ugg.py`
- Test: `tests/test_provider.py`

**Interfaces:**
- Consumes: nothing internal (talks to the internet via its own `httpx.AsyncClient`)
- Produces (`laa.runes.provider`):
  - `Build(primary_style_id: int, sub_style_id: int, perk_ids: list[int], spell_ids: tuple[int, int])` — `perk_ids` is 9 ids: 6 runes then 3 stat shards, LCU order
  - `to_ugg_version(riot_version: str) -> str` — `"15.13.1" -> "15_13"`
  - `parse_overview(data: dict, role: str) -> Build | None`
  - `UGGProvider(http: httpx.AsyncClient | None = None)` with `async get_build(champion_id: int, role: str) -> Build | None` — 5 s timeout, returns `None` on any failure
- **U.GG payload shape is community-reverse-engineered; Step 6 verifies it live and constants live in one block for easy fixing.**

- [ ] **Step 1: Write failing tests**

Create `tests/test_provider.py`:

```python
import httpx

from laa.runes.provider import Build, UGGProvider, parse_overview, to_ugg_version

PERKS = [8112, 8143, 8138, 8135, 8009, 9105]
SHARDS = ["5008", "5008", "5002"]


def make_overview(role_id="5", matches=1000):
    stats = [
        [matches, 600, 8100, 8000, list(PERKS)],   # [0] perks: matches, wins, primary, sub, ids
        [matches, 600, [4, 14]],                    # [1] summoner spells
        None, None, None, None, None, None,         # [2..7] unused by us
        [matches, 600, list(SHARDS)],               # [8] stat shards
    ]
    return {"12": {"10": {role_id: [stats]}}}


def test_to_ugg_version():
    assert to_ugg_version("15.13.1") == "15_13"
    assert to_ugg_version("14.1.5") == "14_1"


def test_parse_overview_exact_role():
    build = parse_overview(make_overview(role_id="5"), "middle")
    assert build == Build(primary_style_id=8100, sub_style_id=8000,
                          perk_ids=PERKS + [5008, 5008, 5002], spell_ids=(4, 14))


def test_parse_overview_falls_back_to_most_played_role():
    data = {"12": {"10": {
        "1": make_overview("1")["12"]["10"]["1"],
    }}}
    data["12"]["10"]["1"][0][0][0] = 5000  # jungle has the most games
    build = parse_overview(data, "middle")  # middle absent -> jungle
    assert build is not None
    assert build.primary_style_id == 8100


def test_parse_overview_garbage_returns_none():
    assert parse_overview({}, "middle") is None
    assert parse_overview({"12": {"10": {}}}, "middle") is None
    assert parse_overview({"12": {"10": {"5": [[]]}}}, "middle") is None


async def test_get_build_via_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if "ddragon" in request.url.host:
            return httpx.Response(200, json=["15.13.1", "15.12.1"])
        assert "stats2.u.gg" in request.url.host
        assert "/overview/15_13/ranked_solo_5x5/103/" in request.url.path
        return httpx.Response(200, json=make_overview())

    provider = UGGProvider(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    build = await provider.get_build(103, "middle")
    assert build is not None and build.spell_ids == (4, 14)


async def test_get_build_returns_none_on_http_error():
    provider = UGGProvider(http=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert await provider.get_build(103, "middle") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_provider.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.runes'`

- [ ] **Step 3: Implement provider**

Create empty `src/laa/runes/__init__.py` and `src/laa/runes/provider.py`:

```python
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
```

Create `scripts/probe_ugg.py`:

```python
"""Live check of the U.GG endpoint constants. Usage: python scripts/probe_ugg.py [champion_id] [role]"""
import asyncio
import sys

sys.path.insert(0, "src")
from laa.runes.provider import UGGProvider  # noqa: E402


async def main() -> None:
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else 103  # Ahri
    role = sys.argv[2] if len(sys.argv) > 2 else "middle"
    build = await UGGProvider().get_build(cid, role)
    print(build)
    if build is None:
        raise SystemExit("FAILED - endpoint or payload shape changed; adjust provider constants")


asyncio.run(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Verify the real endpoint (live probe)**

Run: `.venv\Scripts\python scripts/probe_ugg.py 103 middle`
Expected: prints a `Build(primary_style_id=..., perk_ids=[... 9 ids ...], spell_ids=(...))`, exit code 0.

**If it fails:** the reverse-engineered constants drifted. Debug in this order, changing only the constants block in `provider.py`: (1) print the raw JSON keys — top level should be region ids; adjust `REGION_WORLD`; (2) second level rank ids; adjust `RANK_EMERALD_PLUS`; (3) confirm the trailing `1.5.0.json` API version segment against the requests u.gg's own site makes (browser devtools, filter `stats2.u.gg`); (4) confirm index positions `IDX_PERKS/IDX_SPELLS/IDX_SHARDS`. Re-run the probe until it prints a Build. Unit tests must still pass unmodified (they encode the *structure*, and fixture constants match whatever you fix).

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: U.GG meta build provider with live-verified constants"
```

---

### Task 8: Champion catalog + rune applier

**Files:**
- Create: `src/laa/lcu/catalog.py`, `src/laa/runes/applier.py`
- Test: `tests/test_catalog.py`, `tests/test_applier.py`

**Interfaces:**
- Consumes: LCU request methods (Task 3), `Build` (Task 7), `ordered_spells` (Task 4), `Config` (Task 1), `FakeLCU` (Task 4)
- Produces:
  - `laa.lcu.catalog.ChampionCatalog(lcu)`: `async refresh() -> None` (GET `/lol-game-data/assets/v1/champion-summary.json`), `name(champion_id: int) -> str`, `all() -> dict[int, str]`
  - `laa.runes.applier.RuneApplier(lcu, provider, get_config, get_champion_name: Callable[[int], str])`: `async apply(champion_id: int, role: str) -> None`. Page name `f"LAA: {name}"`; overwrite existing `LAA:` page via PUT else POST new; set current page. Constant `PAGE_PREFIX = "LAA:"`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_catalog.py`:

```python
from laa.lcu.catalog import ChampionCatalog
from tests.helpers import FakeLCU

SUMMARY = ("GET", "/lol-game-data/assets/v1/champion-summary.json")


async def test_refresh_and_lookup():
    lcu = FakeLCU({SUMMARY: [
        {"id": -1, "name": "None"}, {"id": 103, "name": "Ahri"}, {"id": 1, "name": "Annie"},
    ]})
    cat = ChampionCatalog(lcu)
    assert cat.name(103) == "#103"  # before refresh: placeholder
    await cat.refresh()
    assert cat.name(103) == "Ahri"
    assert cat.all() == {103: "Ahri", 1: "Annie"}  # id -1 filtered out
```

Create `tests/test_applier.py`:

```python
from laa.config import Config
from laa.runes.applier import RuneApplier
from laa.runes.provider import Build
from tests.helpers import FakeLCU

PAGES = ("GET", "/lol-perks/v1/pages")
BUILD = Build(primary_style_id=8100, sub_style_id=8000,
              perk_ids=[8112, 8143, 8138, 8135, 8009, 9105, 5008, 5008, 5002],
              spell_ids=(14, 4))

EXPECTED_PAYLOAD = {
    "name": "LAA: Ahri",
    "primaryStyleId": 8100,
    "subStyleId": 8000,
    "selectedPerkIds": BUILD.perk_ids,
    "current": True,
}


class StubProvider:
    def __init__(self, build):
        self.build = build
        self.requests = []

    async def get_build(self, champion_id, role):
        self.requests.append((champion_id, role))
        return self.build


def make_applier(lcu, build=BUILD, **cfg_kw):
    cfg = Config(**{"auto_runes": True, "use_meta_spells": False, **cfg_kw})
    return RuneApplier(lcu, StubProvider(build), lambda: cfg, lambda cid: "Ahri")


async def test_creates_page_when_no_laa_page_exists():
    lcu = FakeLCU({PAGES: [{"id": 1, "name": "my page", "isEditable": True}],
                   ("POST", "/lol-perks/v1/pages"): {"id": 42}})
    await make_applier(lcu).apply(103, "middle")
    assert lcu.sent("POST", "/lol-perks/v1/pages")[0][2] == EXPECTED_PAYLOAD
    assert lcu.sent("PUT", "/lol-perks/v1/currentpage")[0][2] == 42


async def test_overwrites_existing_laa_page():
    lcu = FakeLCU({PAGES: [{"id": 7, "name": "LAA: Yasuo", "isEditable": True}]})
    await make_applier(lcu).apply(103, "middle")
    assert lcu.sent("PUT", "/lol-perks/v1/pages/7")[0][2] == EXPECTED_PAYLOAD
    assert lcu.sent("POST", "/lol-perks/v1/pages") == []
    assert lcu.sent("PUT", "/lol-perks/v1/currentpage")[0][2] == 7


async def test_meta_spells_applied_with_flash_preference():
    lcu = FakeLCU({PAGES: []})
    await make_applier(lcu, use_meta_spells=True, flash_on_f=True).apply(103, "middle")
    sel = lcu.sent("PATCH", "/lol-champ-select/v1/session/my-selection")
    assert sel[0][2] == {"spell1Id": 14, "spell2Id": 4}


async def test_provider_failure_is_silent():
    lcu = FakeLCU()
    await make_applier(lcu, build=None).apply(103, "middle")
    assert lcu.calls == []


async def test_disabled_features_skip_provider():
    lcu = FakeLCU()
    applier = make_applier(lcu, auto_runes=False, use_meta_spells=False)
    await applier.apply(103, "middle")
    assert applier._provider.requests == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_catalog.py tests/test_applier.py`
Expected: FAIL — module not found errors

- [ ] **Step 3: Implement**

Create `src/laa/lcu/catalog.py`:

```python
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SUMMARY_PATH = "/lol-game-data/assets/v1/champion-summary.json"


class ChampionCatalog:
    def __init__(self, lcu) -> None:
        self._lcu = lcu
        self._by_id: dict[int, str] = {}

    async def refresh(self) -> None:
        data = await self._lcu.get(SUMMARY_PATH) or []
        self._by_id = {c["id"]: c["name"] for c in data if c.get("id", -1) > 0}
        log.info("Champion catalog loaded: %d champions", len(self._by_id))

    def name(self, champion_id: int) -> str:
        return self._by_id.get(champion_id, f"#{champion_id}")

    def all(self) -> dict[int, str]:
        return dict(self._by_id)
```

Create `src/laa/runes/applier.py`:

```python
from __future__ import annotations

import logging
from typing import Callable

from laa.config import Config
from laa.core.selection import ordered_spells
from laa.lcu.connector import LCUError
from laa.runes.provider import Build

log = logging.getLogger(__name__)

PAGE_PREFIX = "LAA:"


class RuneApplier:
    def __init__(self, lcu, provider, get_config: Callable[[], Config],
                 get_champion_name: Callable[[int], str]) -> None:
        self._lcu = lcu
        self._provider = provider
        self._get_config = get_config
        self._get_champion_name = get_champion_name

    async def apply(self, champion_id: int, role: str) -> None:
        cfg = self._get_config()
        if not (cfg.auto_runes or cfg.use_meta_spells) or cfg.master_paused:
            return
        build = await self._provider.get_build(champion_id, role)
        if build is None:
            log.warning("No meta build available for %s", self._get_champion_name(champion_id))
            return
        if cfg.auto_runes:
            await self._apply_page(build, champion_id)
        if cfg.use_meta_spells:
            await self._apply_spells(build, cfg)

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
        except LCUError as exc:
            log.warning("Applying rune page failed: %s", exc)

    async def _apply_spells(self, build: Build, cfg: Config) -> None:
        s1, s2 = ordered_spells(build.spell_ids[0], build.spell_ids[1], cfg.flash_on_f)
        try:
            await self._lcu.patch("/lol-champ-select/v1/session/my-selection",
                                  {"spell1Id": s1, "spell2Id": s2})
            log.info("Applied meta summoner spells")
        except LCUError as exc:
            log.warning("Applying meta spells failed: %s", exc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: champion catalog and meta rune page applier"
```

---

### Task 9: Engine orchestration

**Files:**
- Create: `src/laa/core/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: all event types (Task 2), `ReadyCheckAutomation` (Task 5), `ChampSelectAutomation` (Task 6), `RuneApplier.apply` (Task 8), `ChampionCatalog.refresh` (Task 8), LCU `get` (Task 3)
- Produces: `laa.core.engine.Engine`:
  - `__init__(self, lcu, get_config, catalog, rune_applier, notify: Callable[[str], None] | None = None)`
  - `async on_event(self, event: LCUEvent) -> None` — routes events; never raises
  - `phase: str` attribute — current gameflow phase
  - On `Connected`: refresh catalog, GET current gameflow phase to sync, `notify("Connected")`. On `Disconnected`: `notify("Waiting for League client")`. On phase change: reset automations that left their phase, `notify(phase)`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_engine.py`:

```python
from laa.config import Config
from laa.core.engine import Engine
from laa.lcu import events
from tests.helpers import FakeLCU, action, make_session

PHASE = ("GET", "/lol-gameflow/v1/gameflow-phase")
CATALOG = ("GET", "/lol-game-data/assets/v1/champion-summary.json")


class StubApplier:
    def __init__(self):
        self.applied = []

    async def apply(self, cid, role):
        self.applied.append((cid, role))


class StubCatalog:
    def __init__(self):
        self.refreshes = 0

    async def refresh(self):
        self.refreshes += 1

    def all(self):
        return {}


def make_engine(lcu=None, cfg=None):
    lcu = lcu or FakeLCU({PHASE: "None"})
    applier = StubApplier()
    catalog = StubCatalog()
    statuses = []
    eng = Engine(lcu, lambda: cfg or Config(auto_runes=True), catalog, applier,
                 notify=statuses.append)
    return eng, lcu, applier, catalog, statuses


async def test_connected_syncs_catalog_phase_and_status():
    lcu = FakeLCU({PHASE: "Lobby"})
    eng, _, _, catalog, statuses = make_engine(lcu)
    await eng.on_event(events.Connected())
    assert catalog.refreshes == 1
    assert eng.phase == "Lobby"
    assert statuses[-1] == "Connected"


async def test_ready_check_routed_and_reset_on_phase_change():
    eng, lcu, _, _, _ = make_engine()
    await eng.on_event(events.GameflowPhase(phase="ReadyCheck"))
    rc = events.ReadyCheckUpdate(state="InProgress", player_response="None")
    await eng.on_event(rc)
    await eng.on_event(rc)
    accepts = lcu.sent("POST", "/lol-matchmaking/v1/ready-check/accept")
    assert len(accepts) == 1
    # new queue -> new ready check accepted again
    await eng.on_event(events.GameflowPhase(phase="Matchmaking"))
    await eng.on_event(events.GameflowPhase(phase="ReadyCheck"))
    await eng.on_event(rc)
    assert len(lcu.sent("POST", "/lol-matchmaking/v1/ready-check/accept")) == 2


async def test_lock_in_triggers_rune_apply_once_and_resets_next_champ_select():
    eng, lcu, applier, _, _ = make_engine()
    s = make_session(position="middle",
                     actions=[[action(7, 0, "pick", champion_id=103, completed=True)]])
    await eng.on_event(events.GameflowPhase(phase="ChampSelect"))
    await eng.on_event(events.ChampSelectUpdate(session=s))
    await eng.on_event(events.ChampSelectUpdate(session=s))
    assert applier.applied == [(103, "middle")]
    # leave and re-enter champ select -> fires again
    await eng.on_event(events.GameflowPhase(phase="InProgress"))
    await eng.on_event(events.GameflowPhase(phase="ChampSelect"))
    await eng.on_event(events.ChampSelectUpdate(session=s))
    assert applier.applied == [(103, "middle"), (103, "middle")]


async def test_engine_never_raises():
    eng, lcu, _, catalog, _ = make_engine()

    async def boom():
        raise RuntimeError("kaput")

    catalog.refresh = boom
    await eng.on_event(events.Connected())  # must not raise
    assert eng.phase in ("", "None", "Lobby")


async def test_disconnected_status():
    eng, _, _, _, statuses = make_engine()
    await eng.on_event(events.Disconnected())
    assert statuses[-1] == "Waiting for League client"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_engine.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.core.engine'`

- [ ] **Step 3: Implement**

Create `src/laa/core/engine.py`:

```python
from __future__ import annotations

import logging
from typing import Callable

from laa.config import Config
from laa.core.champ_select import ChampSelectAutomation
from laa.core.ready_check import ReadyCheckAutomation
from laa.lcu import events

log = logging.getLogger(__name__)


class Engine:
    """Routes LCU events to automations; owns phase tracking and resets."""

    def __init__(self, lcu, get_config: Callable[[], Config], catalog, rune_applier,
                 notify: Callable[[str], None] | None = None) -> None:
        self._lcu = lcu
        self._catalog = catalog
        self._notify = notify or (lambda text: None)
        self._ready = ReadyCheckAutomation(lcu, get_config)
        self._champ = ChampSelectAutomation(lcu, get_config, on_locked=rune_applier.apply)
        self.phase = ""

    async def on_event(self, event: events.LCUEvent) -> None:
        try:
            await self._dispatch(event)
        except Exception:
            log.exception("Engine error handling %s", type(event).__name__)

    async def _dispatch(self, event: events.LCUEvent) -> None:
        match event:
            case events.Connected():
                await self._catalog.refresh()
                phase = await self._lcu.get("/lol-gameflow/v1/gameflow-phase")
                if isinstance(phase, str):
                    self._set_phase(phase)
                self._notify("Connected")
            case events.Disconnected():
                self._notify("Waiting for League client")
            case events.GameflowPhase(phase=phase):
                self._set_phase(phase)
            case events.ReadyCheckUpdate() as update:
                await self._ready.on_update(update)
            case events.ChampSelectUpdate(session=session):
                await self._champ.on_session(session)

    def _set_phase(self, phase: str) -> None:
        if phase == self.phase:
            return
        if phase != "ReadyCheck":
            self._ready.reset()
        if phase != "ChampSelect":
            self._champ.reset()
        self.phase = phase
        self._notify(phase)
```

Note: `Connected` failures (e.g. catalog refresh raising) are caught by `on_event`'s blanket handler — the `notify("Connected")` may be skipped, but the next gameflow event still updates status.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: engine orchestration with phase-keyed resets"
```

---

### Task 10: Config store, Qt bridge, background worker

**Files:**
- Create: `src/laa/ui/__init__.py`, `src/laa/ui/store.py`, `src/laa/ui/bridge.py`, `src/laa/ui/worker.py`
- Test: `tests/test_store.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `Config`/`load`/`save` (Task 1), `LCUConnector` (Task 3), `Engine` (Task 9), `ChampionCatalog` (Task 8), `UGGProvider` (Task 7), `RuneApplier` (Task 8)
- Produces:
  - `laa.ui.store.ConfigStore(cfg: Config, path: Path | None = None)`: `get() -> Config`, `update(**changes) -> Config` (thread-safe `dataclasses.replace` + save). **`store.get` is the `get_config` closure passed to the engine layer.**
  - `laa.ui.bridge.Bridge(QObject)` signals: `status = Signal(str)`, `log_line = Signal(str)`, `catalog_ready = Signal(object)`; plus `QtLogHandler(bridge)` (a `logging.Handler` emitting `log_line`)
  - `laa.ui.worker.LCUWorker(store, bridge)` — a daemon `threading.Thread`; `run()` hosts the asyncio loop wiring connector → engine and emitting bridge signals

- [ ] **Step 1: Write conftest + failing store test**

Create `tests/conftest.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

Create `tests/test_store.py`:

```python
import json
from pathlib import Path

from laa.config import Config
from laa.ui.store import ConfigStore


def test_update_replaces_and_persists(tmp_path: Path):
    path = tmp_path / "config.json"
    store = ConfigStore(Config(), path)
    before = store.get()
    after = store.update(instalock=True, pick_ids=[103])
    assert after.instalock is True and after.pick_ids == [103]
    assert before.instalock is False          # old snapshot untouched
    assert store.get() is after               # atomic reference swap
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["instalock"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest -q tests/test_store.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.ui'`

- [ ] **Step 3: Implement store, bridge, worker**

Create empty `src/laa/ui/__init__.py`.

Create `src/laa/ui/store.py`:

```python
from __future__ import annotations

import dataclasses
import threading
from pathlib import Path

from laa import config as config_mod
from laa.config import Config


class ConfigStore:
    """Thread-safe config holder. Readers grab an immutable-by-convention snapshot."""

    def __init__(self, cfg: Config, path: Path | None = None) -> None:
        self._cfg = cfg
        self._path = path
        self._lock = threading.Lock()

    def get(self) -> Config:
        return self._cfg

    def update(self, **changes) -> Config:
        with self._lock:
            self._cfg = dataclasses.replace(self._cfg, **changes)
            config_mod.save(self._cfg, self._path)
            return self._cfg
```

Create `src/laa/ui/bridge.py`:

```python
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    """Signals crossing from the asyncio worker thread into the Qt main thread."""

    status = Signal(str)
    log_line = Signal(str)
    catalog_ready = Signal(object)  # dict[int, str]


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: Bridge) -> None:
        super().__init__(level=logging.INFO)
        self._bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._bridge.log_line.emit(self.format(record))
        except RuntimeError:
            pass  # bridge deleted during shutdown
```

Create `src/laa/ui/worker.py`:

```python
from __future__ import annotations

import asyncio
import logging
import threading

from laa.core.engine import Engine
from laa.lcu.catalog import ChampionCatalog
from laa.lcu.connector import LCUConnector
from laa.runes.applier import RuneApplier
from laa.runes.provider import UGGProvider
from laa.ui.bridge import Bridge
from laa.ui.store import ConfigStore

log = logging.getLogger(__name__)


class LCUWorker(threading.Thread):
    """Hosts the asyncio loop running the connector + engine. Daemon: dies with the app."""

    def __init__(self, store: ConfigStore, bridge: Bridge) -> None:
        super().__init__(daemon=True, name="lcu-worker")
        self._store = store
        self._bridge = bridge

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("LCU worker crashed")

    async def _main(self) -> None:
        engine_ref: list[Engine] = []

        async def on_event(event) -> None:
            await engine_ref[0].on_event(event)

        connector = LCUConnector(on_event)
        catalog = ChampionCatalog(connector)
        applier = RuneApplier(connector, UGGProvider(), self._store.get, catalog.name)

        def notify(text: str) -> None:
            self._bridge.status.emit(text)
            if text == "Connected":
                self._bridge.catalog_ready.emit(catalog.all())

        engine_ref.append(Engine(connector, self._store.get, catalog, applier, notify))
        await connector.run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: config store, Qt bridge, background LCU worker"
```

---

### Task 11: Main window + tray icon

**Files:**
- Create: `src/laa/ui/main_window.py`, `src/laa/ui/tray.py`
- Test: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `ConfigStore` (Task 10), `Bridge` (Task 10), `Config` fields (Task 1)
- Produces:
  - `laa.ui.main_window.MainWindow(store: ConfigStore, bridge: Bridge)` — `QMainWindow`; attribute `tray: QSystemTrayIcon | None = None` (set by caller); close button hides to tray when available
  - `laa.ui.main_window.ChampListEditor` — reorderable pick/ban list widget with `changed = Signal(list)`, `set_catalog(dict[int, str])`, `set_ids(list[int])`
  - `laa.ui.main_window.SUMMONER_SPELLS: dict[int, str]`
  - `laa.ui.tray.create_tray(app, window, store) -> QSystemTrayIcon`, `make_icon(paused: bool) -> QIcon`

- [ ] **Step 1: Write failing smoke tests**

Create `tests/test_ui_smoke.py`:

```python
from pathlib import Path

from laa.config import Config
from laa.ui.bridge import Bridge
from laa.ui.main_window import ChampListEditor, MainWindow
from laa.ui.store import ConfigStore


def make_store(tmp_path: Path, **kw) -> ConfigStore:
    return ConfigStore(Config(**kw), tmp_path / "config.json")


def test_window_constructs_and_reacts_to_signals(qtbot, tmp_path):
    store = make_store(tmp_path, pick_ids=[103])
    bridge = Bridge()
    win = MainWindow(store, bridge)
    qtbot.addWidget(win)
    assert win.windowTitle() == "League Auto Accept"
    bridge.status.emit("Connected")
    assert win._status.text() == "Connected"
    bridge.catalog_ready.emit({103: "Ahri", 1: "Annie"})
    assert win._picks._list.item(0).text() == "Ahri"
    bridge.log_line.emit("hello")
    assert "hello" in win._log.toPlainText()


def test_pause_button_writes_config(qtbot, tmp_path):
    store = make_store(tmp_path)
    win = MainWindow(store, Bridge())
    qtbot.addWidget(win)
    win._pause.setChecked(True)
    assert store.get().master_paused is True


def test_champ_list_editor_add_remove_move(qtbot):
    ed = ChampListEditor("Picks")
    qtbot.addWidget(ed)
    ed.set_catalog({103: "Ahri", 1: "Annie", 61: "Orianna"})
    changes: list = []
    ed.changed.connect(changes.append)
    ed._combo.setCurrentIndex(ed._combo.findText("Ahri"))
    ed._add()
    ed._combo.setCurrentIndex(ed._combo.findText("Orianna"))
    ed._add()
    assert changes[-1] == [103, 61]
    ed._list.setCurrentRow(1)
    ed._move(-1)
    assert changes[-1] == [61, 103]
    ed._list.setCurrentRow(0)
    ed._remove()
    assert changes[-1] == [103]


def test_tray_icon_builds(qtbot, tmp_path):
    from laa.ui.tray import make_icon

    assert not make_icon(paused=False).isNull()
    assert not make_icon(paused=True).isNull()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_ui_smoke.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'laa.ui.main_window'`

- [ ] **Step 3: Implement main window**

Create `src/laa/ui/main_window.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
                               QPlainTextEdit, QPushButton, QSlider, QSystemTrayIcon,
                               QTabWidget, QVBoxLayout, QWidget)

from laa.ui.bridge import Bridge
from laa.ui.store import ConfigStore

SUMMONER_SPELLS = {
    1: "Cleanse", 3: "Exhaust", 4: "Flash", 6: "Ghost", 7: "Heal", 11: "Smite",
    12: "Teleport", 13: "Clarity", 14: "Ignite", 21: "Barrier", 32: "Mark",
}
MAX_LIST = 5


class ChampListEditor(QGroupBox):
    changed = Signal(list)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._ids: list[int] = []
        self._names: dict[int, str] = {}
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._list = QListWidget()
        add = QPushButton("Add")
        rm = QPushButton("Remove")
        up = QPushButton("Up")
        down = QPushButton("Down")
        add.clicked.connect(self._add)
        rm.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(+1))
        top = QHBoxLayout()
        top.addWidget(self._combo, 1)
        top.addWidget(add)
        side = QVBoxLayout()
        for b in (rm, up, down):
            side.addWidget(b)
        side.addStretch(1)
        mid = QHBoxLayout()
        mid.addWidget(self._list, 1)
        mid.addLayout(side)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(mid)

    def set_catalog(self, names: dict[int, str]) -> None:
        self._names = names
        self._combo.clear()
        for cid, name in sorted(names.items(), key=lambda kv: kv[1]):
            self._combo.addItem(name, cid)
        self._combo.setCurrentIndex(-1)
        completer = QCompleter([self._combo.itemText(i) for i in range(self._combo.count())])
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._combo.setCompleter(completer)
        self._refresh()

    def set_ids(self, ids: list[int]) -> None:
        self._ids = list(ids)[:MAX_LIST]
        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for cid in self._ids:
            self._list.addItem(self._names.get(cid, f"#{cid}"))

    def _add(self) -> None:
        idx = self._combo.currentIndex()
        if idx < 0:
            idx = self._combo.findText(self._combo.currentText(),
                                       Qt.MatchFlag.MatchFixedString)
        if idx < 0:
            return
        cid = self._combo.itemData(idx)
        if cid is None or cid in self._ids or len(self._ids) >= MAX_LIST:
            return
        self._ids.append(cid)
        self._refresh()
        self.changed.emit(list(self._ids))

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        del self._ids[row]
        self._refresh()
        self.changed.emit(list(self._ids))

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < len(self._ids):
            return
        self._ids[row], self._ids[new] = self._ids[new], self._ids[row]
        self._refresh()
        self._list.setCurrentRow(new)
        self.changed.emit(list(self._ids))


class MainWindow(QMainWindow):
    def __init__(self, store: ConfigStore, bridge: Bridge) -> None:
        super().__init__()
        self._store = store
        self.tray: QSystemTrayIcon | None = None
        self.setWindowTitle("League Auto Accept")
        self.resize(520, 640)
        cfg = store.get()

        self._status = QLabel("Waiting for League client")
        self._pause = QPushButton("Pause")
        self._pause.setCheckable(True)
        self._pause.setChecked(cfg.master_paused)
        self._pause.toggled.connect(lambda on: self._store.update(master_paused=on))

        tabs = QTabWidget()
        tabs.addTab(self._queue_tab(cfg), "Queue")
        tabs.addTab(self._champ_tab(cfg), "Champ Select")
        tabs.addTab(self._runes_tab(cfg), "Runes")

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(100)
        self._log.setFixedHeight(120)

        central = QWidget()
        lay = QVBoxLayout(central)
        row = QHBoxLayout()
        row.addWidget(self._status, 1)
        row.addWidget(self._pause)
        lay.addLayout(row)
        lay.addWidget(tabs, 1)
        lay.addWidget(self._log)
        self.setCentralWidget(central)

        bridge.status.connect(self._status.setText)
        bridge.log_line.connect(self._log.appendPlainText)
        bridge.catalog_ready.connect(self._on_catalog)

    def _queue_tab(self, cfg) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        auto = QCheckBox("Auto-accept ready check")
        auto.setChecked(cfg.auto_accept)
        auto.toggled.connect(lambda on: self._store.update(auto_accept=on))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 10)
        slider.setValue(int(cfg.accept_delay_s))
        self._delay_label = QLabel(f"{int(cfg.accept_delay_s)} s")
        slider.valueChanged.connect(self._on_delay)
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(self._delay_label)
        form.addRow(auto)
        form.addRow("Accept delay", row)
        return w

    def _on_delay(self, value: int) -> None:
        self._delay_label.setText(f"{value} s")
        self._store.update(accept_delay_s=float(value))

    def _champ_tab(self, cfg) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._picks = ChampListEditor("Pick priority (top first)")
        self._picks.set_ids(cfg.pick_ids)
        self._picks.changed.connect(lambda ids: self._store.update(pick_ids=ids))
        self._bans = ChampListEditor("Ban priority (top first)")
        self._bans.set_ids(cfg.ban_ids)
        self._bans.changed.connect(lambda ids: self._store.update(ban_ids=ids))

        instalock = QCheckBox("Instalock (lock pick immediately)")
        instalock.setChecked(cfg.instalock)
        instalock.toggled.connect(lambda on: self._store.update(instalock=on))

        spells = QCheckBox("Set summoner spells")
        spells.setChecked(cfg.set_spells)
        spells.toggled.connect(lambda on: self._store.update(set_spells=on))
        spell1 = self._spell_combo(cfg.spell1_id, "spell1_id")
        spell2 = self._spell_combo(cfg.spell2_id, "spell2_id")
        flash_f = QCheckBox("Flash on F")
        flash_f.setChecked(cfg.flash_on_f)
        flash_f.toggled.connect(lambda on: self._store.update(flash_on_f=on))
        srow = QHBoxLayout()
        srow.addWidget(spells)
        srow.addWidget(spell1)
        srow.addWidget(spell2)
        srow.addWidget(flash_f)

        msg = QLineEdit(cfg.lobby_message)
        msg.setPlaceholderText("Lobby chat message (empty = off)")
        msg.editingFinished.connect(lambda: self._store.update(lobby_message=msg.text()))

        lay.addWidget(self._picks, 1)
        lay.addWidget(self._bans, 1)
        lay.addWidget(instalock)
        lay.addLayout(srow)
        lay.addWidget(msg)
        return w

    def _spell_combo(self, current: int, field_name: str) -> QComboBox:
        combo = QComboBox()
        for sid, name in sorted(SUMMONER_SPELLS.items(), key=lambda kv: kv[1]):
            combo.addItem(name, sid)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(
            lambda _i: self._store.update(**{field_name: combo.currentData()}))
        return combo

    def _runes_tab(self, cfg) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        runes = QCheckBox("Auto-import meta runes when my pick locks in")
        runes.setChecked(cfg.auto_runes)
        runes.toggled.connect(lambda on: self._store.update(auto_runes=on))
        meta_spells = QCheckBox("Also use meta summoner spells")
        meta_spells.setChecked(cfg.use_meta_spells)
        meta_spells.toggled.connect(lambda on: self._store.update(use_meta_spells=on))
        note = QLabel("Runes are written to a page named 'LAA: <Champion>'.\n"
                      "If the meta fetch fails, your current runes are left untouched.")
        note.setWordWrap(True)
        lay.addWidget(runes)
        lay.addWidget(meta_spells)
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    def _on_catalog(self, names: dict) -> None:
        self._picks.set_catalog(names)
        self._bans.set_catalog(names)

    def closeEvent(self, event) -> None:
        if self.tray is not None and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            if not self._store.get().tray_hint_shown:
                self._store.update(tray_hint_shown=True)
                self.tray.showMessage("Still running",
                                      "League Auto Accept keeps working in the tray. "
                                      "Right-click the icon to quit.")
        else:
            super().closeEvent(event)
```

- [ ] **Step 4: Implement tray**

Create `src/laa/ui/tray.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from laa.ui.main_window import MainWindow
from laa.ui.store import ConfigStore


def make_icon(paused: bool) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#5b5a56") if paused else QColor("#c89b3c"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setPen(QColor("#0a1428"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(28)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "LA")
    painter.end()
    return QIcon(pm)


def create_tray(app: QApplication, window: MainWindow, store: ConfigStore) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(make_icon(store.get().master_paused), parent=app)
    menu = QMenu()
    pause = menu.addAction("Pause")
    pause.setCheckable(True)
    pause.setChecked(store.get().master_paused)

    def on_pause(checked: bool) -> None:
        store.update(master_paused=checked)
        tray.setIcon(make_icon(checked))

    pause.toggled.connect(on_pause)
    show = menu.addAction("Show window")
    show.triggered.connect(lambda: (window.showNormal(), window.activateWindow()))
    menu.addSeparator()
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray._menu = menu  # keep a python-side reference so the menu isn't GC'd
    tray.activated.connect(
        lambda reason: window.showNormal()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.setToolTip("League Auto Accept")
    tray.show()
    return tray
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass (offscreen Qt from conftest)

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: main window with tabs, champ list editors, and tray icon"
```

---

### Task 12: Entry point, packaging, docs

**Files:**
- Create: `src/laa/__main__.py`, `scripts/make_icon.py`, `assets/icon.ico` (generated), `build.ps1`, `README.md`, `docs/testing.md`
- Test: manual smoke (Step 4) + full suite

**Interfaces:**
- Consumes: everything (Tasks 1–11)
- Produces: `python -m laa` launches the app; `build.ps1` produces `dist/LeagueAutoAccept.exe`

- [ ] **Step 1: Implement entry point**

Create `src/laa/__main__.py`:

```python
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from laa import config
from laa.ui.bridge import Bridge, QtLogHandler
from laa.ui.main_window import MainWindow
from laa.ui.store import ConfigStore
from laa.ui.tray import create_tray
from laa.ui.worker import LCUWorker

MUTEX_NAME = "Global\\LeagueAutoAcceptPy"
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def setup_logging() -> None:
    config.config_dir().mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        config.config_dir() / "laa.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


def main() -> int:
    app = QApplication(sys.argv)
    if not acquire_single_instance():
        QMessageBox.warning(None, "League Auto Accept", "League Auto Accept is already running.")
        return 1
    setup_logging()
    app.setQuitOnLastWindowClosed(False)

    store = ConfigStore(config.load())
    bridge = Bridge()
    logging.getLogger("laa").addHandler(QtLogHandler(bridge))

    window = MainWindow(store, bridge)
    window.tray = create_tray(app, window, store)
    LCUWorker(store, bridge).start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Generate the icon**

Create `scripts/make_icon.py`:

```python
"""Generate assets/icon.ico (run once; the .ico is committed)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path("assets")
out.mkdir(exist_ok=True)
img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse((16, 16, 240, 240), fill="#c89b3c")
try:
    font = ImageFont.truetype("arialbd.ttf", 110)
except OSError:
    font = ImageFont.load_default()
draw.text((128, 118), "LA", font=font, fill="#0a1428", anchor="mm")
img.save(out / "icon.ico", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
print("wrote", out / "icon.ico")
```

Run: `.venv\Scripts\python scripts/make_icon.py`
Expected: `wrote assets\icon.ico`

- [ ] **Step 3: Write build script, README, manual test checklist**

Create `build.ps1`:

```powershell
$ErrorActionPreference = "Stop"
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name LeagueAutoAccept --icon assets\icon.ico --paths src `
  src\laa\__main__.py
Write-Host "Built dist\LeagueAutoAccept.exe"
```

Create `README.md`:

```markdown
# League Auto Accept (Python)

A Python rebuild of [sweetriverfish/LeagueAutoAccept](https://github.com/sweetriverfish/LeagueAutoAccept)
with a GUI, system tray, and automatic meta rune import.

## Features
- Auto-accept the ready check (optional delay)
- Champ select: pick & ban from ordered fallback lists, optional instalock
- Summoner spell assignment with Flash-key (D/F) preference
- One-time lobby chat message
- **Auto meta runes:** when your pick locks in, the current meta rune page and
  (optionally) summoner spells for that champion/role are fetched from U.GG and
  written to a rune page named `LAA: <Champion>` — your other pages are never touched
- Everything individually toggleable; master pause in the system tray

## Run
Download `LeagueAutoAccept.exe` from releases and run it (the League client must be
running), or from source:

    python -m venv .venv
    .venv\Scripts\python -m pip install -e .
    .venv\Scripts\python -m laa

## Build the exe
    .venv\Scripts\python -m pip install -e ".[dev]"
    .\build.ps1

## Notes
- Windows only.
- Config and logs live in `%APPDATA%\LeagueAutoAccept\`.
- League Auto Accept isn't endorsed by Riot Games and doesn't reflect the views or
  opinions of Riot Games or anyone officially involved in producing or managing
  League of Legends. LCU automation of this kind is tolerated on most servers but
  violates Korean server policy — use at your own risk.
```

Create `docs/testing.md`:

```markdown
# Manual integration checklist

Run against the real League client (a practice-tool or draft lobby). Check off each:

- [ ] App starts with client closed -> status "Waiting for League client"; no errors
- [ ] Start League client -> status flips to Connected; champion names appear in pickers
- [ ] Queue up -> ready check auto-accepted (try delay 0 and delay 3 s)
- [ ] Master pause on -> ready check NOT accepted
- [ ] Draft lobby: ban list top choice gets banned
- [ ] Pick list: top choice hovered; with instalock on, locked
- [ ] First pick banned by someone else -> falls through to second choice
- [ ] Summoner spells set; "Flash on F" places Flash on F
- [ ] Lobby message posted exactly once
- [ ] On lock-in: rune page "LAA: <Champion>" created and selected; re-lock next game
      overwrites the same page (no page-slot leak)
- [ ] Kill the League client mid-lobby -> app returns to "Waiting for League client",
      reconnects when client restarts
- [ ] Close button hides to tray (hint shown once); tray Quit exits; second app copy
      shows "already running" and exits
- [ ] `%APPDATA%\LeagueAutoAccept\laa.log` contains the session's actions
```

- [ ] **Step 4: Full suite + manual smoke**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

Run: `.venv\Scripts\python -m laa`
Expected: window opens, tray icon appears, status shows "Waiting for League client" (or "Connected" if the client is running). Close the window — app stays in tray. Quit from tray.

- [ ] **Step 5: Build the exe and smoke it**

Run: `.\build.ps1`
Expected: `dist\LeagueAutoAccept.exe` exists. Launch it once: window + tray appear.

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: entry point, PyInstaller build, README and manual test checklist"
```

---

## Post-plan verification

- Work through `docs/testing.md` against the real client (requires the user's League install; coordinate with the user for the in-queue items).
- Run the superpowers:requesting-code-review skill before calling the project done.
