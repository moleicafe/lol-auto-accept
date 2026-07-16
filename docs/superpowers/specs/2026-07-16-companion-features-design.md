# v1.2.0 Companion features — Design

**Date:** 2026-07-16
**Status:** Approved by user (this session)
**Builds on:** the existing app architecture (LCU connector → engine → automations; op.gg
provider → BuildApplier; PySide6 UI). See prior specs in this folder.

## Goal

Five small features that deepen the app's identity — automating the boring parts between
and around games — using only the LCU and data the app already fetches. No overlays.

## Features

### 1. Skill order in the item set

`parse_champion` additionally extracts:
- **max order** from `skill_masteries[0].ids` picked by highest `play` (e.g. `["Q","W","E"]`),
- **start order** = first 4 entries of the highest-play `skills[*].order`.

`Build` gains `skill_max: list[str]` and `skill_start: list[str]` (empty lists when absent;
`compare=False` like `items`). The item-set **Core block title** becomes
`"Core — max Q>W>E (start W-Q-E-Q)"` (max joined with `>`, start with `-`; omit either
half if empty, plain `"Core"` if both empty). No new config, no new UI, no new requests.

### 2. Auto-honor (default ON)

New config `auto_honor: bool = True`; checkbox on the **App** tab ("Auto-honor a teammate
after game"). New automation hook on gameflow phase **`PreEndOfGame`** (engine calls a new
`EndOfGameAutomation.on_phase(phase)`):
- GET `/lol-honor-v2/v1/ballot` → `eligibleAllies` (fall back to `eligiblePlayers` filtered
  to allies if the field is absent).
- Pick one at random, POST `/lol-honor-v2/v1/honor-player` with
  `{"summonerId": <id>, "honorCategory": "HEART"}` (include `puuid` when present).
- Once per game (guard flag reset on leaving the end-of-game phases). Silent-degrade: any
  LCUError/shape surprise is logged and skipped. The ballot schema must be **verified live**
  once (like item sets); the POST body fields are the single adjustment point.

### 3. Auto play-again (default OFF)

New config `auto_play_again: bool = False`; checkbox on the **Queue** tab ("After game,
return to lobby (Play Again)") with note "never starts the queue". On gameflow phase
**`EndOfGame`**: POST `/lol-lobby/v2/play-again`, once per game (same automation class +
guard). Explicitly does NOT start matchmaking. Silent-degrade.

### 4. Counter-ban suggestions (log-only, no config)

During champ select **planning/early** phase, if the user has a pick list: fetch the meta
build for `pick_ids[0]` + assigned role via the existing provider (this also **warms a
cache**: `BuildApplier.apply` for the same champion+role at lock-in reuses it instead of
re-fetching). From the build's new `counter_ids: list[tuple[int, float]]`
(champion_id, winrate-vs-us; parsed from the payload `counters` field: `win/play`, minimum
20 games, top 3 by winrate) log once per champ select:
`"Counters to <Champ> worth banning: <Name> (54%), <Name> (52%), <Name> (51%)"` — names via
the champion catalog. Informational only; the ban logic is unchanged. Provider caching:
`OPGGProvider` keeps the last `(champion_id, position) → data` fetch (size-1 cache) so the
double fetch costs one request.

### 5. Lobby multisearch ("Scout lobby")

New **"Scout lobby"** button (Champ Select tab) + config `multisearch_auto: bool = False`
("Auto-open on champ select") checkbox beside it. Behavior (button click, or automatically
once per champ select when the toggle is on):
- Read ally `summonerId`s from the champ-select session (`myTeam`), excluding the local player.
- GET `/lol-summoner/v2/summoners/{id}` per ally → `gameName#tagLine`.
- Region: GET `/riotclient/region-locale` → `region` (lowercased; fall back to `na`).
- Open `https://op.gg/multisearch/{region}?summoners=<comma-separated URL-encoded Riot IDs>`
  via `QDesktopServices.openUrl` (UI side) — the worker only assembles the URL and emits a
  new `Bridge.multisearch_ready(url)` signal / the button asks the worker via a small
  queued request. Simplest architecture: the engine caches the latest champ-select session;
  a `MultisearchBuilder` in `laa/core` builds the URL on demand (pure except LCU GETs);
  UI button triggers it via a thread-safe callable exposed by the worker
  (`asyncio.run_coroutine_threadsafe` on the worker loop) and opens the returned URL.
- Silent-degrade: any failure logs; anonymized/missing names are skipped; no allies resolvable
  → log "no lobby names available".

## Cross-cutting

- All automations follow the established pattern: per-feature config gate + master pause,
  independent try/except with silent-degrade, Qt-free in `laa/core`/`laa/runes`.
- New gameflow hooks route through the engine like existing ones (phase-keyed reset).
- Version → **1.2.0**; README + testing checklist updated; release after live verification
  of the honor ballot schema.

## Testing

- Provider: skill-order + counters parsing (fixtures extended); provider fetch-cache test
  (second `get_build` for same champ+position does one HTTP request).
- Applier: Core block title includes max/start order; falls back to "Core" when absent.
- End-of-game automation: honors once on PreEndOfGame with random eligible ally (seeded
  random / injected chooser), respects `auto_honor` + pause, resets per game; play-again
  POSTs once on EndOfGame only when enabled; both silent on LCUError.
- Counter suggestions: logged once per champ select with correct names/percentages; no log
  when pick list empty or counters absent.
- Multisearch: URL assembly from a fake session + fake summoner lookups (encoding, region
  fallback, ally exclusion); UI smoke: button exists, auto toggle writes config.
- Live verification before release: honor ballot schema; multisearch URL opens correctly.

## Risks

- Honor ballot/POST schema is community-documented, not yet live-verified → single
  construction site + verify step, silent-degrade otherwise.
- Early counter fetch adds one op.gg request per champ select (mitigated: cache reuse at
  lock-in usually nets zero extra).
- Multisearch teammate names may be anonymized in some queues → skip missing, degrade to
  fewer names.
