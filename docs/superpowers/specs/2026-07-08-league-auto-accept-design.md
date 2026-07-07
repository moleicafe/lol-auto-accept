# League Auto Accept (Python rebuild) — Design

**Date:** 2026-07-08
**Status:** Approved by user (this session)

## Goal

Rebuild [sweetriverfish/LeagueAutoAccept](https://github.com/sweetriverfish/LeagueAutoAccept) (C# console app, .NET 9) as a modern Python desktop app: same core automation, a proper GUI with system-tray support, and one new headline feature — automatic meta rune/spell import for the locked-in champion.

Windows-only, packaged as a standalone `.exe` (PyInstaller). Requires the League of Legends client to be running; the app idles gracefully when it isn't.

## Features

### Ported from the original
1. **Auto-accept ready check** — accept the queue popup, with an optional configurable delay (0–10 s).
2. **Champ select pick/ban** — an ordered fallback list (1–5 champions) for picks and another for bans. The app declares (hovers) the top available choice and works down the list if a champion is banned, taken, or unowned. Optional **instalock** (lock immediately) vs. hover-only.
3. **Summoner spell assignment** — two configured spells, with a "Flash on D / Flash on F" preference.
4. **Lobby chat message** — optional configurable message posted once to champ-select chat.
5. Every automation is **individually toggleable**; a master pause/resume lives in the tray menu and the main window.

### New
6. **Auto meta runes + spells on lock-in** — when the player's champion is locked, fetch the current meta rune page and summoner spells for that champion/assigned role from U.GG's public stats endpoint and write them to a dedicated rune page named `LAA: <Champion>` (created or overwritten — never touches the user's other pages), then set it as the active page. If the fetch or mapping fails for any reason, log it, leave the player's current runes untouched, and never delay or block the pick.

### Non-goals (explicitly out of scope)
- Per-role pick/ban lists (declined by user)
- ARAM bench sniping, notifications, auto re-queue, auto honor (declined by user)
- macOS/Linux support
- Anything requiring the Riot public (api.riotgames.com) API key — the app talks only to the local client plus the rune data source

## Architecture

Three layers with one-way event flow: **LCU connector → automation engine → GUI** (the GUI writes config; the engine reads it).

```
┌────────────┐  typed events   ┌──────────────────┐  state signals  ┌─────────────┐
│ LCU        │ ───────────────►│ Automation engine │ ───────────────►│ PySide6 GUI │
│ connector  │ ◄─────────────── │ (state machine)  │ ◄─────────────── │ + tray icon │
└────────────┘  HTTP actions   └──────────────────┘   config (JSON)  └─────────────┘
```

The connector and engine run on a background thread inside an asyncio event loop. The GUI runs Qt's event loop on the main thread. Cross-thread communication uses Qt signals (engine → UI) and a thread-safe config snapshot (UI → engine).

### 1. LCU connector (`src/laa/lcu/`)

- **Discovery:** poll (every ~2 s while disconnected) for the `LeagueClientUx.exe` process and parse `--app-port` and `--remoting-auth-token` from its command line (via `wmic`/`Get-CimInstance` subprocess or `psutil`). No lockfile-path guessing needed.
- **HTTP:** `httpx.AsyncClient` against `https://127.0.0.1:<port>`, basic auth `riot:<token>`, TLS verification disabled (client uses a self-signed cert).
- **Websocket:** `wss://127.0.0.1:<port>/` (same auth) subscribed to `OnJsonApiEvent`; the connector filters and re-emits typed events:
  - `GameflowPhase(phase)` — from `lol-gameflow_v1_gameflow-phase`
  - `ReadyCheck(state)` — from `lol-matchmaking_v1_ready-check`
  - `ChampSelectSession(session)` — from `lol-champ-select_v1_session`
  - `Connected` / `Disconnected`
- **Resilience:** if the websocket drops or the process dies, emit `Disconnected` and return to discovery polling. All request helpers raise a single `LCUError` the engine can catch.

Key endpoints used (all local LCU):
- `POST /lol-matchmaking/v1/ready-check/accept`
- `GET /lol-champ-select/v1/session`, `PATCH /lol-champ-select/v1/session/actions/{id}`
- `GET /lol-champ-select/v1/pickable-champion-ids`, `GET /lol-champ-select/v1/bannable-champion-ids`
- `PATCH /lol-champ-select/v1/session/my-selection` (summoner spells)
- `GET/POST/PUT /lol-perks/v1/pages`, `PUT /lol-perks/v1/currentpage`
- `GET/POST /lol-chat/v1/conversations` (find champ-select conversation, post message)
- `GET /lol-game-data/assets/...` or `GET /lol-champions/v1/...` (champion id/name catalog — sourced from the client, no external static-data dependency)

### 2. Automation engine (`src/laa/core/`)

A state machine keyed on gameflow phase. Pure asyncio + connector calls; no Qt imports, fully unit-testable with fake events.

- **`ReadyCheck` phase:** if auto-accept enabled and ready-check state is `InProgress`, wait the configured delay, then accept. Accept once per ready-check (track a handled flag reset on phase change).
- **`ChampSelect` phase:** on each session update, compute pending actions belonging to the local player (`localPlayerCellId`):
  - *Ban action:* choose the first ban-list champion that is bannable and not already banned; declare + complete.
  - *Pick action:* choose the first pick-list champion that is pickable (owned, not banned, not taken); declare (hover) always; complete (lock) only if instalock is on.
  - *Spells:* set once per champ select.
  - *Chat:* post the lobby message once per champ select (find the `championSelect` conversation).
  - *Runes (new):* when the local player's pick action is `completed`, trigger the rune provider once for that champion + assigned position.
  - Idempotency: track which sub-tasks have run for the current champ-select session and reset when the phase leaves champ select.
- **Any other phase:** idle.
- Every sub-task checks its config toggle and the master pause flag immediately before acting; failures are logged and never crash the loop.

### 3. Rune provider (`src/laa/runes/`)

- **Source:** U.GG's public stats JSON (the same community-documented `stats2.u.gg` overview endpoint used by open-source rune importers). The exact URL shape and JSON schema must be **verified at implementation time** (a dedicated plan task); the provider is an interface (`get_build(champion_id, role) -> Build | None`) so the source can be swapped if U.GG changes.
- **Mapping:** U.GG perk IDs are Riot perk IDs, so the mapping to an LCU rune page is direct: primary style, sub-style, 6 perk selections, 3 stat shards. Summoner spells come from the same payload.
- **Application:** delete any existing page whose name starts with `LAA:`, then create `LAA: <Champion>` and set it current. If the account has no free page slot, overwrite the previous `LAA:` page in place instead of failing.
- **Failure policy:** timeout 5 s; on any error return `None` — the engine logs "meta runes unavailable" and moves on. Spells from the provider are applied only if the user enabled "use meta spells" (otherwise the static configured spells win).

### 4. GUI (`src/laa/ui/`)

PySide6. One main window, ~500×600:

- **Status bar section:** client connection state (Disconnected / Connected / In queue / Champ select / In game), last action log line, master pause button.
- **Queue tab:** auto-accept toggle + delay slider.
- **Champ select tab:** pick list and ban list editors (search box with champion-name autocomplete from the LCU catalog, reorderable list of up to 5), instalock toggle, summoner spell pickers + flash-key preference, lobby message text field.
- **Runes tab:** auto-runes toggle, "also use meta summoner spells" toggle, status of last import.
- **Tray icon:** left-click shows/hides window; menu = Pause/Resume, Show, Quit. Closing the window minimizes to tray (with a first-time hint); Quit exits.
- A small activity log panel (last ~100 events) at the bottom of the window.

### Config (`src/laa/config.py`)

JSON at `%APPDATA%\LeagueAutoAccept\config.json`, dataclass-backed, written atomically on change, versioned with a `schema_version` field. Missing/corrupt config → defaults + warning. Champion references stored by ID with cached display names.

## Error handling

- Client not running → status "Waiting for League client", automations idle. No errors surfaced as popups.
- Client restarts → connector reconnects automatically.
- LCU request failures (races: someone else banned your target mid-request, dodge mid-action) → caught per sub-task, logged, next session update retries naturally.
- Rune fetch failures → silent degrade (log only), never block picking.
- Single-instance guard (named mutex) so two copies don't fight over actions.
- Logs to `%APPDATA%\LeagueAutoAccept\laa.log` (rotating, 1 MB × 3).

## Testing

- **Unit tests (pytest, no client needed):** pick/ban fallback selection against synthetic champ-select sessions (banned/taken/unowned cases, hover vs. instalock), ready-check idempotency, rune payload → LCU page mapping, config load/migrate/corrupt-file handling.
- **Connector tests:** a fake local LCU (aiohttp test server + websocket) exercising discovery-retry, auth, event dispatch, and reconnect.
- **Manual integration checklist:** documented in `docs/testing.md` — real-client verification of accept, pick/ban, spells, chat, runes in a practice-tool/normal lobby (can't be CI'd).

## Packaging

- `pyproject.toml` project (`laa` package), Python 3.12+.
- Dependencies: `PySide6`, `httpx`, `websockets`, `psutil`.
- `build.ps1` → PyInstaller one-file, windowed, custom icon → `dist/LeagueAutoAccept.exe`.
- README with usage, the standard "not endorsed by Riot Games" disclaimer, and the same gray-area note the original carries (LCU automation is tolerated on most servers but violates Korean server policy).

## Risks

- **U.GG endpoint is unofficial** and may change shape — mitigated by the provider interface, implementation-time verification, and silent-degrade policy.
- **LCU endpoint drift** across client patches — mitigated by using long-stable endpoints (the same ones the C# original and other community tools rely on).
- **PyInstaller + PySide6 size** (~50 MB exe) — accepted trade-off, matches user's distribution choice.
