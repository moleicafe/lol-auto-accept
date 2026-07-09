# Safety-lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "safety-lock" that auto-locks the user's champion a configurable margin before the champ-select pick timer expires, as a third pick behavior alongside hover-only and instalock.

**Architecture:** Pure timing/target logic goes in `laa/core/selection.py` (Qt-free, unit-tested). `ChampSelectAutomation` computes the lock deadline from the session timer snapshot and schedules a single asyncio task that re-reads the live session at fire time before locking. Two new config fields and two new champ-select-tab controls.

**Tech Stack:** Python 3.12, asyncio, PySide6, pytest / pytest-asyncio / pytest-qt.

**Spec:** `docs/superpowers/specs/2026-07-09-safety-lock-design.md`

## Global Constraints

- Windows-only; package under `src/laa/`; tests under `tests/`. `laa/core` stays Qt-free.
- New config fields: `safety_lock: bool = False`, `safety_lock_buffer_s: float = 1.0` (UI slider range 0–5s).
- Safety-lock acts only when: it is the local player's in-progress, not-completed pick turn, **`instalock` is off**, `safety_lock` is on, **not** master-paused, and the pick timer is finite (`timer.isInfinite` false, `timer.phase == "BAN_PICK"`, `timer.adjustedTimeLeftInPhase` present).
- It locks the champion currently hovered in the local pick action (`championId` > 0), else the first available from the pick list (`choose_pick`), else nothing.
- At fire time it re-reads `GET /lol-champ-select/v1/session` and only locks if the pick action still exists, is in progress, and is not completed. All LCU calls caught (`LCUError`); the task never crashes the loop.
- `reset()` cancels any pending safety-lock task.
- All tests run with `.venv\Scripts\python -m pytest -q` from the project root; commit after every task.

---

### Task 1: Config fields

**Files:**
- Modify: `src/laa/config.py` (add two fields to `Config`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: existing `Config`, `load`, `save`
- Produces: `Config.safety_lock: bool` (default `False`), `Config.safety_lock_buffer_s: float` (default `1.0`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_safety_lock_defaults(tmp_path):
    cfg = load(tmp_path / "missing.json")
    assert cfg.safety_lock is False
    assert cfg.safety_lock_buffer_s == 1.0


def test_safety_lock_roundtrip(tmp_path):
    cfg = Config(safety_lock=True, safety_lock_buffer_s=2.5)
    save(cfg, tmp_path / "c.json")
    assert load(tmp_path / "c.json") == cfg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_config.py -k safety_lock`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'safety_lock'`

- [ ] **Step 3: Add the fields**

In `src/laa/config.py`, in the `Config` dataclass, add these two lines in the `# champ select` block right after `instalock: bool = False`:

```python
    instalock: bool = False
    safety_lock: bool = False
    safety_lock_buffer_s: float = 1.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q tests/test_config.py`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: add safety_lock config fields"
```

---

### Task 2: Pure timing & target helpers

**Files:**
- Modify: `src/laa/core/selection.py` (add two functions)
- Modify: `tests/helpers.py` (extend `make_session` with timer fields)
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: existing `my_active_actions`, `choose_pick` in `selection.py`
- Produces:
  - `selection.pick_time_left_s(session: dict) -> float | None`
  - `selection.lock_target(session: dict, pick_list: list[int], pickable: set[int]) -> int | None`
  - `tests.helpers.make_session(..., time_left_ms: int | None = None, timer_infinite: bool = False, phase: str = "BAN_PICK")`

- [ ] **Step 1: Extend the shared test helper**

Replace the `make_session` function in `tests/helpers.py` with this (adds optional timer params; default output is unchanged from before):

```python
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
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_selection.py` (it already imports `action, make_session` from `tests.helpers`). Add this new import line near the top and the tests below:

```python
from laa.core.selection import lock_target, pick_time_left_s


def test_pick_time_left_finite():
    assert pick_time_left_s(make_session(time_left_ms=27000)) == 27.0


def test_pick_time_left_infinite_is_none():
    assert pick_time_left_s(make_session(time_left_ms=27000, timer_infinite=True)) is None


def test_pick_time_left_missing_is_none():
    assert pick_time_left_s(make_session()) is None


def test_pick_time_left_non_pick_phase_is_none():
    assert pick_time_left_s(make_session(time_left_ms=27000, phase="FINALIZATION")) is None


def test_lock_target_prefers_live_hover():
    s = make_session(actions=[[action(7, 0, "pick", champion_id=103, in_progress=True)]])
    assert lock_target(s, [61], {61, 103}) == 103


def test_lock_target_falls_back_to_pick_list():
    s = make_session(actions=[[action(7, 0, "pick", in_progress=True)]])  # no hover
    assert lock_target(s, [61, 245], {245, 61}) == 61


def test_lock_target_none_when_no_pick_turn():
    assert lock_target(make_session(), [61], {61}) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_selection.py -k "pick_time_left or lock_target"`
Expected: FAIL — `ImportError: cannot import name 'lock_target'`

- [ ] **Step 4: Implement the helpers**

Append to `src/laa/core/selection.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass (existing tests still green — `make_session`'s default output is unchanged)

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: pick_time_left_s and lock_target selection helpers"
```

---

### Task 3: Safety-lock scheduling in ChampSelectAutomation

**Files:**
- Modify: `src/laa/core/champ_select.py`
- Test: `tests/test_champ_select.py`

**Interfaces:**
- Consumes: `selection.pick_time_left_s`, `selection.lock_target`, `selection.my_active_actions`, `selection.flat_actions` (Task 2); `Config.safety_lock`, `Config.safety_lock_buffer_s`, `Config.instalock`, `Config.master_paused` (Task 1); `LCUError`
- Produces: `ChampSelectAutomation._safety_task: asyncio.Task | None`; methods `_arm_safety_lock`, `_cancel_safety`, `_safety_lock_after`, `_fire_safety_lock`; `reset()` now cancels the task; `on_session` arms it

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_champ_select.py`. It already has `import`s for `Config`, `ChampSelectAutomation`, `FakeLCU`, `action`, `make_session`, and the constant `PICKABLE = ("GET", "/lol-champ-select/v1/pickable-champion-ids")` and helpers `lcu_with(...)` and `cfg(**kw)`. Add `import asyncio` at the top and this block:

```python
SESSION = ("GET", "/lol-champ-select/v1/session")


def hovered_session(cid=103, ms=1000):
    return make_session(actions=[[action(7, 0, "pick", champion_id=cid, in_progress=True)]],
                        time_left_ms=ms)


async def test_safety_lock_locks_hovered_champ():
    s = hovered_session()
    lcu = FakeLCU({SESSION: s, PICKABLE: [103, 245]})
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[]))
    await auto.on_session(s)          # delay = 1.0 - 1.0 = 0
    await auto._safety_task           # run the scheduled lock
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")[-1] == (
        "PATCH", "/lol-champ-select/v1/session/actions/7",
        {"championId": 103, "completed": True})


async def test_safety_lock_falls_back_to_pick_list_when_no_hover():
    s = make_session(actions=[[action(7, 0, "pick", in_progress=True)]], time_left_ms=1000)
    lcu = FakeLCU({SESSION: s, PICKABLE: [245]})
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[245]))
    await auto.on_session(s)
    await auto._safety_task
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")[-1] == (
        "PATCH", "/lol-champ-select/v1/session/actions/7",
        {"championId": 245, "completed": True})


async def test_no_safety_task_when_instalock():
    s = hovered_session()
    auto = ChampSelectAutomation(
        FakeLCU({SESSION: s, PICKABLE: [103]}),
        lambda: cfg(safety_lock=True, instalock=True, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_no_safety_task_when_safety_disabled():
    s = hovered_session()
    auto = ChampSelectAutomation(FakeLCU({SESSION: s}),
                                 lambda: cfg(safety_lock=False, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_no_safety_task_when_not_my_pick_turn():
    s = make_session(time_left_ms=1000)  # no actions -> not my turn
    auto = ChampSelectAutomation(FakeLCU({SESSION: s}),
                                 lambda: cfg(safety_lock=True, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_no_safety_task_when_timer_infinite():
    s = make_session(actions=[[action(7, 0, "pick", champion_id=103, in_progress=True)]],
                     time_left_ms=1000, timer_infinite=True)
    auto = ChampSelectAutomation(FakeLCU({SESSION: s}),
                                 lambda: cfg(safety_lock=True, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_safety_lock_skips_if_already_locked_at_fire_time():
    arming = hovered_session()  # in progress when armed
    fired = make_session(  # completed by the time the task fires
        actions=[[action(7, 0, "pick", champion_id=103, completed=True)]], time_left_ms=1000)
    lcu = FakeLCU({SESSION: fired, PICKABLE: [103]})
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[]))
    await auto.on_session(arming)
    await auto._safety_task
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7") == []


async def test_reset_cancels_pending_safety_task():
    s = make_session(actions=[[action(7, 0, "pick", champion_id=103, in_progress=True)]],
                     time_left_ms=30000)  # 30s -> long delay, task stays pending
    auto = ChampSelectAutomation(
        FakeLCU({SESSION: s, PICKABLE: [103]}),
        lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[]))
    await auto.on_session(s)
    task = auto._safety_task
    assert task is not None and not task.done()
    auto.reset()
    await asyncio.sleep(0)  # let the cancellation propagate
    assert task.cancelled()
    assert auto._safety_task is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_champ_select.py -k safety`
Expected: FAIL — `AttributeError: 'ChampSelectAutomation' object has no attribute '_safety_task'`

- [ ] **Step 3: Implement the scheduling**

In `src/laa/core/champ_select.py`:

1. Add `import asyncio` at the top (below `import logging`).

2. Replace the `reset` method with this (adds task cancellation; safe on first call from `__init__` via `getattr`):

```python
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
```

3. In `on_session`, add the arm call as the last line:

```python
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
```

4. Add these four methods to the class (e.g., after `_notify_lock`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass (the 8 new safety tests plus all existing champ-select and other tests). No "Task was destroyed but it is pending" warnings — the reset test cancels its task and the delay-0 tests are awaited.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: safety-lock scheduling in champ select automation"
```

---

### Task 4: UI controls on the Champ Select tab

**Files:**
- Modify: `src/laa/ui/main_window.py`
- Test: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `ConfigStore.update`, `Config.safety_lock`, `Config.safety_lock_buffer_s`
- Produces: `MainWindow._safety` (QCheckBox), `MainWindow._safety_buf` (QSlider), `MainWindow._on_safety_buffer`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py` (it already has `make_store`, `MainWindow`, `Bridge`, `qtbot`):

```python
def test_safety_lock_controls_write_config(qtbot, tmp_path):
    store = make_store(tmp_path)
    win = MainWindow(store, Bridge())
    qtbot.addWidget(win)
    win._safety.setChecked(True)
    assert store.get().safety_lock is True
    win._safety_buf.setValue(3)
    assert store.get().safety_lock_buffer_s == 3.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest -q tests/test_ui_smoke.py -k safety_lock`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_safety'`

- [ ] **Step 3: Add the controls**

In `src/laa/ui/main_window.py`, in `_champ_tab`, replace the instalock block:

```python
        instalock = QCheckBox("Instalock (lock pick immediately)")
        instalock.setChecked(cfg.instalock)
        instalock.toggled.connect(lambda on: self._store.update(instalock=on))
```

with this (adds the safety-lock checkbox and buffer slider directly under instalock):

```python
        instalock = QCheckBox("Instalock (lock pick immediately)")
        instalock.setChecked(cfg.instalock)
        instalock.toggled.connect(lambda on: self._store.update(instalock=on))

        self._safety = QCheckBox("Auto-lock before timer runs out")
        self._safety.setChecked(cfg.safety_lock)
        self._safety.toggled.connect(lambda on: self._store.update(safety_lock=on))
        self._safety_buf = QSlider(Qt.Orientation.Horizontal)
        self._safety_buf.setRange(0, 5)
        self._safety_buf.setValue(int(cfg.safety_lock_buffer_s))
        self._safety_buf_label = QLabel(f"{int(cfg.safety_lock_buffer_s)} s")
        self._safety_buf.valueChanged.connect(self._on_safety_buffer)
        safety_row = QHBoxLayout()
        safety_row.addWidget(QLabel("Lock buffer"))
        safety_row.addWidget(self._safety_buf, 1)
        safety_row.addWidget(self._safety_buf_label)
```

Then, still in `_champ_tab`, replace the layout line `lay.addWidget(instalock)` with:

```python
        lay.addWidget(instalock)
        lay.addWidget(self._safety)
        lay.addLayout(safety_row)
```

And add this method to the class (next to `_on_delay`):

```python
    def _on_safety_buffer(self, value: int) -> None:
        self._safety_buf_label.setText(f"{value} s")
        self._store.update(safety_lock_buffer_s=float(value))
```

`QSlider`, `QLabel`, `QHBoxLayout`, `QCheckBox`, and `Qt` are already imported in this file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Manual smoke (optional, needs no client)**

Run: `.venv\Scripts\python -m laa` — the Champ Select tab shows "Auto-lock before timer runs out" with a "Lock buffer" slider under Instalock. Close the window / quit from the tray.

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: safety-lock checkbox and buffer slider on champ select tab"
```

---

## Post-plan verification

- Add the safety-lock line to the README feature list and the manual checklist in `docs/testing.md` (a checkbox: "hover a pick, don't lock; with safety-lock on and buffer 1s, it auto-locks ~1s before the timer expires; with instalock on it still locks instantly").
- Run superpowers:requesting-code-review before calling the feature done.
- Manual integration test against the real client: draft lobby, hover a champion, let the timer run down, confirm it locks ~buffer seconds before 0 and that auto-runes still fire afterward.
