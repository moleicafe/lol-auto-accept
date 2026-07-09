# Safety-lock (auto-lock before the pick timer expires) — Design

**Date:** 2026-07-09
**Status:** Approved by user (this session)
**Feature added to:** the existing [League Auto Accept](2026-07-08-league-auto-accept-design.md) app.

## Goal

Add a third champ-select pick behavior between the current two (instalock = lock
instantly; instalock off = hover only, never auto-lock): a **safety-lock** that
hovers normally but automatically locks the pick a short, configurable margin
before the champ-select pick timer would expire. This lets the user wait/trade or
be AFK without missing the lock, and avoids the exact-0 edge where client/network
lag can cause a failed lock.

## Behavior

- New independent setting **`safety_lock`** (bool, default off) and a **buffer**
  **`safety_lock_buffer_s`** (float seconds, default **1.0**, UI range 0–5s).
- Safety-lock acts only when **all** hold: it is the local player's pick turn (a
  pick action of theirs is `isInProgress` and not `completed`), **instalock is
  off**, `safety_lock` is on, and the pick timer is finite. If instalock is on it
  already locks instantly, so safety-lock does nothing.
- While the above holds, the app schedules a lock to fire `safety_lock_buffer_s`
  seconds before the pick timer reaches 0.
- **What it locks (at fire time):** the champion currently hovered in the local
  player's pick action (`action.championId` if > 0 — this respects a last-second
  manual hover change). If nothing is hovered, it falls back to the first
  available champion from the user's pick priority list. If neither exists, it
  does nothing (cannot lock an empty slot) and logs that it skipped.
- After a successful lock, the completed pick appears on the next session update
  and the **existing auto-rune import** fires through the normal `on_locked` path
  — no change to that flow.
- Master pause and the per-feature toggles are honored: paused, or `safety_lock`
  off, means no scheduling and any pending lock is cancelled.

### Why scheduled, not polled

The League client does not push a champ-select session update every second, so the
countdown cannot be observed purely from events (an event may arrive at 20s left
and then none until someone acts). Instead the app reads the timer snapshot from
the session (`timer.adjustedTimeLeftInPhase`, milliseconds) and schedules a single
asyncio task to fire at `now + time_left - buffer`. Every session update that still
meets the conditions **re-arms** the task with the freshest timer value (cancel
previous, schedule new); leaving champ select or any disqualifying condition
**cancels** it.

## Non-goals

- No change to instalock or to the ban flow.
- No safety-lock for bans (bans already auto-complete via the existing ban logic).
- Does not try to lock during the client's own auto-resolution at exactly 0 — the
  buffer exists precisely to act before that.

## Architecture

The change is contained to the champ-select layer plus config and one UI tab.
Pure timing/target logic goes in `selection.py` (Qt-free, no I/O, unit-tested); the
scheduling and the LCU write stay in `ChampSelectAutomation`.

### 1. Config (`src/laa/config.py`)

Two new dataclass fields:
- `safety_lock: bool = False`
- `safety_lock_buffer_s: float = 1.0`

### 2. Pure helpers (`src/laa/core/selection.py`)

- `pick_time_left_s(session) -> float | None` — returns the finite seconds left in
  the current pick phase from `session["timer"]`, or `None` when the timer is
  missing, `isInfinite` is true, or the phase is not a pick phase (`"BAN_PICK"`).
- `lock_target(session, pick_list, pickable) -> int | None` — the champion the
  safety-lock should lock: the local player's in-progress pick action's
  `championId` if > 0 (the live hover), else `choose_pick(pick_list, session,
  pickable)`, else `None`.

`choose_pick`, `my_active_actions`, and `assigned_position` already exist and are
reused.

### 3. Automation (`src/laa/core/champ_select.py`)

New per-session state (initialized/cleared in `reset()`):
- `self._safety_task: asyncio.Task | None = None`

Flow, added at the end of `on_session` (after the existing hover/ban/spells/chat):
- `_arm_safety_lock(cfg, session)`:
  - If not (`cfg.safety_lock` and not `cfg.instalock`), or master paused, or there
    is no in-progress-not-completed local pick action, or `pick_time_left_s` is
    `None`, or the pick is already completed → **cancel** any pending task and
    return.
  - Otherwise compute `delay = max(0, pick_time_left_s(session) -
    cfg.safety_lock_buffer_s)`, cancel any existing `_safety_task`, and schedule
    `_safety_task = asyncio.create_task(self._safety_lock_after(delay, action_id))`.
- `_safety_lock_after(delay, action_id)`: `await asyncio.sleep(delay)` then call
  `_fire_safety_lock(action_id)`.
- `_fire_safety_lock(action_id)`:
  - Read fresh config via `self._get_config()`.
  - `GET /lol-champ-select/v1/session` for the live state.
  - Re-validate: the local pick action `action_id` still exists, is in progress,
    and is not completed; config still has `safety_lock` on, `instalock` off, not
    paused. If any fails → log and return (someone locked, dodged, phase changed).
  - Ensure the pickable set is loaded (reuse `self._pickable`, fetching
    `GET /lol-champ-select/v1/pickable-champion-ids` if it is not yet cached) so the
    pick-list fallback can be evaluated; the live-hover case does not need it.
  - Determine `cid = lock_target(session, cfg.pick_ids, self._pickable)`; if `None`,
    log "nothing to safety-lock" and return.
  - `PATCH /lol-champ-select/v1/session/actions/{action_id}` with
    `{"championId": cid, "completed": True}`. Log the lock.
  - Wrap LCU calls in `try/except LCUError`; never crash the loop.

`reset()` cancels `self._safety_task` if pending and sets it to `None`.

The task runs on the same asyncio loop as `on_session` (the worker loop), so
`asyncio.create_task` is valid from within the awaited `on_session`.

### 4. UI (`src/laa/ui/main_window.py`)

On the **Champ Select** tab, directly under the Instalock checkbox:
- A checkbox **"Auto-lock before timer runs out"** bound to `safety_lock`.
- A labeled slider for the buffer (0–5s, shown as e.g. "1 s"), bound to
  `safety_lock_buffer_s`, using the same slider pattern as the existing accept-delay
  control (integer seconds; stored as float). Matches the tab's existing style.

## Error handling

- Fire-time re-validation via a fresh `GET session` means the safety-lock never
  overrides a manual lock, never acts after a dodge, and never fires in the wrong
  phase.
- All LCU calls in the new paths are caught (`LCUError`) and logged; a failure
  leaves the user's pick untouched and never crashes the worker.
- Cancelling `_safety_task` on `reset()` and on every re-arm prevents stale tasks
  from firing into a new champ select.
- If the timer is infinite or absent, safety-lock simply does not arm.

## Testing

**Pure (`tests/test_selection.py`), no client:**
- `pick_time_left_s`: finite BAN_PICK timer → seconds; `isInfinite` → None; missing
  timer → None; non-pick phase → None.
- `lock_target`: live hover present → that id; no hover but pick list available →
  first available; neither → None.

**Automation (`tests/test_champ_select.py`), FakeLCU + monkeypatched
`asyncio.sleep`:**
- With `safety_lock` on, instalock off, local pick in progress, finite timer: after
  the (patched, immediate) sleep, it PATCHes `completed:true` for the hovered champ.
- Falls back to the pick list when nothing is hovered.
- No-op / no scheduling when: instalock on; `safety_lock` off; master paused; not
  the local player's turn; pick already completed.
- Fire-time re-validation: if the session read at fire time shows the pick already
  completed (or not in progress), it does not PATCH.
- `reset()` cancels a pending `_safety_task`.

**UI (`tests/test_ui_smoke.py`):** toggling the checkbox writes `safety_lock`; moving
the buffer slider writes `safety_lock_buffer_s`.

## Risks

- **Timer field semantics.** `timer.adjustedTimeLeftInPhase` is assumed to reflect
  the current pick turn's remaining time during `BAN_PICK`. If a client patch
  changes this, safety-lock would fire early/late — mitigated by the fire-time
  re-validation (it still only locks a valid in-progress pick) and the buffer.
  Verified against the live client in the manual checklist.
- **Clock drift** between the snapshot and local monotonic clock is sub-second and
  well within the buffer.
