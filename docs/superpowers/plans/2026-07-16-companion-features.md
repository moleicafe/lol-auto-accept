# v1.2.0 Companion Features Implementation Plan

> Executed inline (same-session) task-by-task with TDD. Spec (authoritative for endpoints,
> field names, defaults, formats): `docs/superpowers/specs/2026-07-16-companion-features-design.md`

**Goal:** Skill order in item sets, auto-honor, auto play-again, counter-ban suggestions, lobby multisearch.

**Global constraints:** established app patterns — per-feature config gate + master pause; independent try/except silent-degrade; `laa/core` & `laa/runes` Qt-free; commit per task; full suite green each task; version 1.2.0 at the end.

### Task 1: Config fields
- Modify `src/laa/config.py`: `auto_honor: bool = True`, `auto_play_again: bool = False`, `multisearch_auto: bool = False`.
- Test `tests/test_config.py`: defaults + roundtrip (pattern of existing tests).

### Task 2: Skill order — provider parse + item-set title
- Modify `src/laa/runes/provider.py`: `Build.skill_max: list[str]`, `Build.skill_start: list[str]` (default `[]`, `compare=False`); parse per spec §1 (highest-play `skill_masteries[].ids`; first 4 of highest-play `skills[].order`); defensive → empty lists.
- Modify `src/laa/runes/applier.py`: `core_block_title(skill_max, skill_start) -> str` pure helper (`"Core — max Q>W>E (start W-Q-E-Q)"`, graceful halves); `make_item_set` gains optional `core_title: str` arg used by `_apply_item_set`.
- Tests: provider parse fixtures; title formatting incl. empty cases; applier passes title through to the PUT document.

### Task 3: Provider counters + fetch cache
- Modify `src/laa/runes/provider.py`: `Build.counter_ids: list[tuple[int, float]]` (default `[]`, `compare=False`) — top 3 by winrate (`win/play`), min 20 play, from `counters`; size-1 fetch cache on `OPGGProvider` keyed `(champion_id, position)`.
- Tests: counters parse (min-play filter, sort, cap 3); cache test via MockTransport counting exe... counting requests (2× get_build same champ+position → 1 HTTP fetch); different position → refetch.

### Task 4: End-of-game automation (honor + play-again)
- Create `src/laa/core/end_of_game.py`: `EndOfGameAutomation(lcu, get_config, choose=random.choice)` with `reset()` and `async on_phase(phase)`. `PreEndOfGame` → honor per spec §2 (ballot GET, random eligible ally, honor POST, once per game). `EndOfGame` → play-again POST per spec §3 (once, only if `auto_play_again`). Guards reset when phase leaves the end-of-game pair.
- Modify `src/laa/core/engine.py`: instantiate, route phases to it, reset on `_set_phase` like others.
- Tests `tests/test_end_of_game.py`: honors once w/ injected chooser; respects `auto_honor`/pause; ballot empty/LCUError silent; play-again once only when enabled; per-game reset via engine phase cycling.

### Task 5: Counter-ban suggestions
- Modify `src/laa/runes/applier.py`: `async suggest_counters(champion_id, role)` — get_build (warms cache), log once-style message per spec §4 with catalog names + win %.
- Modify `src/laa/core/champ_select.py`: optional `on_planning: Callable[[int, str], Awaitable[None]]`; during PLANNING with non-empty `pick_ids`, call once per champ select with `(pick_ids[0], assigned_position)`.
- Modify `src/laa/core/engine.py`: wire `on_planning=applier.suggest_counters`.
- Tests: champ_select fires on_planning once (and not when pick list empty); applier logs suggestion (caplog) and skips silently when counters empty/build None.

### Task 6: Lobby multisearch
- Create `src/laa/core/scout.py`: `LobbyScout(lcu, get_config)` with `async build_url(session) -> str | None` (ally summonerIds from cached session's myTeam minus local, summoner name lookups, region via `/riotclient/region-locale` fallback `na`, URL per spec §5) and session caching via `update_session(session)`.
- Modify `src/laa/core/engine.py`: hold scout, feed it champ-select sessions; on entering ChampSelect with `multisearch_auto`, schedule auto scout → `on_url` callback.
- Modify `src/laa/ui/worker.py`: wire scout; `request_multisearch()` (thread-safe, `run_coroutine_threadsafe`); `Bridge.multisearch_ready = Signal(str)`.
- Modify `src/laa/ui/main_window.py`: "Scout lobby" button + "Auto-open on champ select" checkbox (Champ Select tab); `multisearch_ready` → `QDesktopServices.openUrl`.
- Tests: build_url from fake session/lookups (exclusion, encoding, region fallback, None when no allies); engine auto-trigger gated by config; UI smoke (button exists, checkbox writes config).

### Post-plan
README + docs/testing.md updates; code review; merge; version 1.2.0; rebuild + relaunch; push; release (after live honor-schema verification).
