# Auto Item Sets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On champion lock-in, write a meta item set ("build") to the League client from the op.gg data already fetched for runes, so it appears in the in-game shop.

**Architecture:** The op.gg provider parses item id lists into a new `ItemBuild` (Qt-free, pure); the applier — renamed `RuneApplier` → `BuildApplier` since it now applies the whole meta build — builds the LCU item-set document with a pure helper and writes it (read whole document → drop prior `LAA:` sets → append → PUT). One op.gg fetch per lock-in serves runes, spells, and items.

**Tech Stack:** Python 3.12, httpx, PySide6, pytest / pytest-asyncio / pytest-qt.

**Spec:** `docs/superpowers/specs/2026-07-15-auto-item-sets-design.md`

## Global Constraints

- Windows-only; package under `src/laa/`; tests under `tests/`. `laa/runes/` stays Qt-free.
- New config field `auto_items: bool = True`, gated independently (like `auto_runes`).
- Item set titled `LAA: <Champion>` (reuse `applier.PAGE_PREFIX == "LAA:"`), `associatedChampions: [<championId>]`; item IDs in blocks are **strings**.
- Never modify the user's own item sets: read the full item-set document, drop only sets whose `title` starts with `LAA:`, append the new one, PUT the whole document back.
- Silent-degrade: every LCU/parse failure in the item path is caught and logged; it never blocks the pick. Item write only when a champion is locked, `auto_items` on, master pause off.
- Blocks (in order, each omitted if empty): **Starters**, **Core**, **Boots**, **Situational** (top `SITUATIONAL_COUNT = 6` from `last_items`, deduped against earlier blocks).
- All tests run with `.venv\Scripts\python -m pytest -q` from the project root; commit after every task.

---

### Task 1: Config field `auto_items`

**Files:**
- Modify: `src/laa/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.auto_items: bool` (default `True`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_auto_items_default_and_roundtrip(tmp_path: Path):
    assert load(tmp_path / "missing.json").auto_items is True
    cfg = Config(auto_items=False)
    save(cfg, tmp_path / "c.json")
    assert load(tmp_path / "c.json").auto_items is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest -q tests/test_config.py -k auto_items`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'auto_items'`

- [ ] **Step 3: Add the field**

In `src/laa/config.py`, in the `# runes` block, add `auto_items` right after `auto_runes`:

```python
    # runes
    auto_runes: bool = True
    auto_items: bool = True
    use_meta_spells: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q tests/test_config.py`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: add auto_items config field"
```

---

### Task 2: Provider — parse item build

**Files:**
- Modify: `src/laa/runes/provider.py`
- Test: `tests/test_provider.py`

**Interfaces:**
- Consumes: existing `parse_champion`, `Build`
- Produces:
  - `ItemBuild(starter_ids: list[int], core_ids: list[int], boots_ids: list[int], situational_ids: list[int])` (frozen dataclass) with method `is_empty() -> bool`
  - `SITUATIONAL_COUNT = 6`
  - `parse_item_build(data: dict) -> ItemBuild`
  - `Build.items: ItemBuild | None` (default `None`, `compare=False` so existing rune equality tests are unaffected); `parse_champion` now sets it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_provider.py` (its imports already include `from laa.runes.provider import ...`; add the new names):

```python
from laa.runes.provider import ItemBuild, SITUATIONAL_COUNT, parse_item_build


def _items_payload():
    return {
        "starter_items": [
            {"ids": [1056, 2003], "play": 100},
            {"ids": [1054], "play": 999},           # highest play -> chosen
        ],
        "core_items": [{"ids": [3118, 4645, 3157], "play": 500}],
        "boots": [{"ids": [3020], "play": 300}, {"ids": [3111], "play": 10}],
        "last_items": [
            {"ids": [3157], "play": 90},            # dup of a core item -> skipped
            {"ids": [3089], "play": 80},
            {"ids": [3135], "play": 70},
            {"ids": [3165], "play": 60},
            {"ids": [3116], "play": 50},
            {"ids": [3102], "play": 40},
            {"ids": [3040], "play": 30},
            {"ids": [3041], "play": 20},            # 7th unique -> beyond cap of 6
        ],
    }


def test_parse_item_build_picks_top_and_dedupes():
    build = parse_item_build(_items_payload())
    assert build.starter_ids == [1054]              # highest play
    assert build.core_ids == [3118, 4645, 3157]
    assert build.boots_ids == [3020]
    # 3157 skipped (in core); capped at SITUATIONAL_COUNT, in play order
    assert build.situational_ids == [3089, 3135, 3165, 3116, 3102, 3040]
    assert len(build.situational_ids) == SITUATIONAL_COUNT
    assert not build.is_empty()


def test_parse_item_build_empty_when_no_item_fields():
    build = parse_item_build({})
    assert build == ItemBuild([], [], [], [])
    assert build.is_empty()


def test_parse_champion_attaches_items():
    data = {
        "runes": [{"primary_page_id": 8100, "secondary_page_id": 8200,
                   "primary_rune_ids": [1, 2, 3, 4], "secondary_rune_ids": [5, 6],
                   "stat_mod_ids": [7, 8, 9], "play": 5}],
        "summoner_spells": [{"ids": [4, 14], "play": 5}],
        **_items_payload(),
    }
    from laa.runes.provider import parse_champion
    build = parse_champion(data)
    assert build is not None
    assert build.items == ItemBuild([1054], [3118, 4645, 3157], [3020],
                                    [3089, 3135, 3165, 3116, 3102, 3040])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_provider.py -k "item_build or attaches_items"`
Expected: FAIL — `ImportError: cannot import name 'ItemBuild'`

- [ ] **Step 3: Implement**

In `src/laa/runes/provider.py`:

1. Change the dataclass import: `from dataclasses import dataclass, field`.

2. Add the constant near the other op.gg constants (after `DEFAULT_POSITION`):

```python
SITUATIONAL_COUNT = 6  # how many late-game items to include in the Situational block
```

3. Add the `ItemBuild` dataclass and `parse_item_build` above `parse_champion`, and give `Build` an `items` field:

```python
@dataclass(frozen=True)
class ItemBuild:
    starter_ids: list[int]
    core_ids: list[int]
    boots_ids: list[int]
    situational_ids: list[int]

    def is_empty(self) -> bool:
        return not (self.starter_ids or self.core_ids
                    or self.boots_ids or self.situational_ids)


def _top_item_ids(entries) -> list[int]:
    entries = entries or []
    if not entries:
        return []
    best = max(entries, key=lambda e: e.get("play", 0))
    return [int(i) for i in best.get("ids", [])]


def parse_item_build(data: dict) -> ItemBuild:
    starter = _top_item_ids(data.get("starter_items"))
    core = _top_item_ids(data.get("core_items"))
    boots = _top_item_ids(data.get("boots"))
    shown = set(starter) | set(core) | set(boots)
    situational: list[int] = []
    for entry in sorted(data.get("last_items") or [],
                        key=lambda e: e.get("play", 0), reverse=True):
        for raw in entry.get("ids", []):
            iid = int(raw)
            if iid not in shown and iid not in situational:
                situational.append(iid)
        if len(situational) >= SITUATIONAL_COUNT:
            break
    return ItemBuild(starter, core, boots, situational[:SITUATIONAL_COUNT])
```

Add the field to `Build` (note `compare=False`):

```python
@dataclass(frozen=True)
class Build:
    primary_style_id: int
    sub_style_id: int
    perk_ids: list[int]           # 6 runes (4 primary + 2 secondary) + 3 stat shards, LCU order
    spell_ids: tuple[int, int]
    items: "ItemBuild | None" = field(default=None, compare=False)
```

4. In `parse_champion`, after computing `spell_ids` and before `return Build(...)`, parse items defensively and pass them:

```python
        try:
            items = parse_item_build(data)
        except (KeyError, IndexError, TypeError, ValueError):
            items = None
        return Build(
            primary_style_id=int(top["primary_page_id"]),
            sub_style_id=int(top["secondary_page_id"]),
            perk_ids=perk_ids,
            spell_ids=spell_ids,
            items=items,
        )
```

(`ItemBuild` must be defined before `Build` references it in the annotation string — placing `ItemBuild`/`parse_item_build` above `Build` as shown satisfies this. If `Build` is currently defined above `parse_champion`, move the `ItemBuild` dataclass above `Build`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass (existing rune-equality tests unaffected because `items` has `compare=False`)

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: parse op.gg item build into ItemBuild"
```

---

### Task 3: Pure item-set document builder

**Files:**
- Modify: `src/laa/runes/applier.py` (add pure module-level functions only; class rename is Task 4)
- Test: `tests/test_applier.py`

**Interfaces:**
- Consumes: `ItemBuild` (Task 2), `PAGE_PREFIX`
- Produces:
  - `make_item_set(champion_id: int, title: str, item_build: ItemBuild) -> dict`
  - `item_set_document(existing_doc: dict, champion_id: int, title: str, item_build: ItemBuild) -> dict`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_applier.py` (add imports at top):

```python
from laa.runes.applier import PAGE_PREFIX, item_set_document, make_item_set
from laa.runes.provider import ItemBuild

ITEMS = ItemBuild(starter_ids=[1054], core_ids=[3118, 4645, 3157],
                  boots_ids=[3020], situational_ids=[3089, 3135])


def test_make_item_set_shape():
    s = make_item_set(103, "LAA: Ahri", ITEMS)
    assert s["title"] == "LAA: Ahri"
    assert s["associatedChampions"] == [103]
    assert s["type"] == "custom"
    types = [b["type"] for b in s["blocks"]]
    assert types == ["Starters", "Core", "Boots", "Situational"]
    # item ids are strings with count
    assert s["blocks"][1]["items"] == [
        {"id": "3118", "count": 1}, {"id": "4645", "count": 1}, {"id": "3157", "count": 1}]


def test_make_item_set_omits_empty_blocks():
    s = make_item_set(1, "LAA: Annie", ItemBuild([], [3020], [], []))
    assert [b["type"] for b in s["blocks"]] == ["Core"]


def test_item_set_document_keeps_user_sets_and_replaces_laa():
    existing = {"itemSets": [
        {"title": "My build", "blocks": []},
        {"title": "LAA: Yasuo", "blocks": []},
    ], "timestamp": 123}
    doc = item_set_document(existing, 103, "LAA: Ahri", ITEMS)
    titles = [s["title"] for s in doc["itemSets"]]
    assert "My build" in titles          # user set kept
    assert "LAA: Yasuo" not in titles    # stale LAA set dropped
    assert titles.count("LAA: Ahri") == 1
    assert doc["timestamp"] == 123       # other document fields preserved
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_applier.py -k "item_set or make_item_set"`
Expected: FAIL — `ImportError: cannot import name 'item_set_document'`

- [ ] **Step 3: Implement**

In `src/laa/runes/applier.py`, add these module-level functions (after `PAGE_PREFIX`), and add `from laa.runes.provider import Build, ItemBuild` (extend the existing provider import):

```python
def _item_block(block_type: str, ids: list[int]) -> dict:
    return {"type": block_type, "items": [{"id": str(i), "count": 1} for i in ids]}


def make_item_set(champion_id: int, title: str, item_build: ItemBuild) -> dict:
    blocks = []
    if item_build.starter_ids:
        blocks.append(_item_block("Starters", item_build.starter_ids))
    if item_build.core_ids:
        blocks.append(_item_block("Core", item_build.core_ids))
    if item_build.boots_ids:
        blocks.append(_item_block("Boots", item_build.boots_ids))
    if item_build.situational_ids:
        blocks.append(_item_block("Situational", item_build.situational_ids))
    return {
        "title": title,
        "type": "custom",
        "map": "any",
        "mode": "any",
        "sortrank": 0,
        "startedFrom": "blank",
        "associatedChampions": [champion_id],
        "associatedMaps": [],
        "preferredItemSlots": [],
        "blocks": blocks,
    }


def item_set_document(existing_doc: dict, champion_id: int, title: str,
                      item_build: ItemBuild) -> dict:
    doc = dict(existing_doc) if isinstance(existing_doc, dict) else {}
    kept = [s for s in (doc.get("itemSets") or [])
            if not str(s.get("title", "")).startswith(PAGE_PREFIX)]
    kept.append(make_item_set(champion_id, title, item_build))
    doc["itemSets"] = kept
    return doc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: pure LCU item-set document builder"
```

---

### Task 4: BuildApplier — write the item set (and rename)

**Files:**
- Modify: `src/laa/runes/applier.py` (rename class, add item-set method, extend `apply`)
- Modify: `src/laa/ui/worker.py` (import/instantiate the renamed class)
- Test: `tests/test_applier.py`

**Interfaces:**
- Consumes: `make_item_set`/`item_set_document` (Task 3), `Build.items`/`ItemBuild` (Task 2), `Config.auto_items` (Task 1)
- Produces: class `BuildApplier` (replaces `RuneApplier`; same constructor) whose `apply` also writes an item set when `auto_items` is on

- [ ] **Step 1: Update existing applier tests for the rename + new default**

In `tests/test_applier.py`:
- Change `from laa.runes.applier import RuneApplier` → `from laa.runes.applier import BuildApplier` (keep the Task-3 imports).
- In `make_applier`, change `RuneApplier(...)` → `BuildApplier(...)`.
- Update `test_disabled_features_skip_provider` to also disable items (otherwise `auto_items` now defaults `True` and the provider is called):

```python
async def test_disabled_features_skip_provider():
    lcu = FakeLCU()
    applier = make_applier(lcu, auto_runes=False, use_meta_spells=False, auto_items=False)
    await applier.apply(103, "middle")
    assert applier._provider.requests == []
```

- [ ] **Step 2: Write the failing item-set tests**

Add to `tests/test_applier.py`:

```python
SUMMONER = ("GET", "/lol-summoner/v1/current-summoner")
SETS = ("GET", "/lol-item-sets/v1/item-sets/55/sets")

BUILD_WITH_ITEMS = Build(
    primary_style_id=8100, sub_style_id=8000,
    perk_ids=[8112, 8143, 8138, 8135, 8009, 9105, 5008, 5008, 5002],
    spell_ids=(14, 4), items=ITEMS)


async def test_item_set_written_keeping_user_sets():
    lcu = FakeLCU({
        PAGES: [],
        SUMMONER: {"summonerId": 55},
        SETS: {"itemSets": [{"title": "My build", "blocks": []},
                            {"title": "LAA: Old", "blocks": []}], "timestamp": 1},
    })
    await make_applier(lcu, build=BUILD_WITH_ITEMS, auto_runes=False).apply(103, "middle")
    puts = lcu.sent("PUT", "/lol-item-sets/v1/item-sets/55/sets")
    assert len(puts) == 1
    titles = [s["title"] for s in puts[0][2]["itemSets"]]
    assert titles == ["My build", "LAA: Ahri"]  # user kept, old LAA dropped, new appended


async def test_no_item_set_when_auto_items_off():
    lcu = FakeLCU({PAGES: [], SUMMONER: {"summonerId": 55}, SETS: {"itemSets": []}})
    await make_applier(lcu, build=BUILD_WITH_ITEMS, auto_items=False).apply(103, "middle")
    assert lcu.sent("PUT", "/lol-item-sets/v1/item-sets/55/sets") == []


async def test_no_item_set_when_build_has_no_items():
    lcu = FakeLCU({PAGES: [], SUMMONER: {"summonerId": 55}, SETS: {"itemSets": []}})
    await make_applier(lcu, build=BUILD).apply(103, "middle")  # BUILD.items is None
    assert lcu.sent("GET", "/lol-summoner/v1/current-summoner") == []


async def test_item_set_write_failure_is_silent():
    from laa.lcu.connector import LCUError
    lcu = FakeLCU({PAGES: [], SUMMONER: {"summonerId": 55}, SETS: {"itemSets": []}})
    lcu.errors[("PUT", "/lol-item-sets/v1/item-sets/55/sets")] = LCUError("500")
    await make_applier(lcu, build=BUILD_WITH_ITEMS, auto_runes=False).apply(103, "middle")
    # did not raise; a rune/spell path (disabled here) is unaffected
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest -q tests/test_applier.py`
Expected: FAIL — `ImportError: cannot import name 'BuildApplier'`

- [ ] **Step 4: Implement — rename class and add item write**

In `src/laa/runes/applier.py`, rename `class RuneApplier:` → `class BuildApplier:` and update `apply`, then add `_apply_item_set`:

```python
    async def apply(self, champion_id: int, role: str) -> None:
        cfg = self._get_config()
        if not (cfg.auto_runes or cfg.use_meta_spells or cfg.auto_items) or cfg.master_paused:
            return
        build = await self._provider.get_build(champion_id, role)
        if build is None:
            log.warning("No meta build available for %s", self._get_champion_name(champion_id))
            return
        if cfg.auto_runes:
            await self._apply_page(build, champion_id)
        if cfg.use_meta_spells:
            await self._apply_spells(build, cfg)
        if cfg.auto_items:
            await self._apply_item_set(build, champion_id)
```

Add the method (after `_apply_spells`):

```python
    async def _apply_item_set(self, build: Build, champion_id: int) -> None:
        if build.items is None or build.items.is_empty():
            return
        title = f"{PAGE_PREFIX} {self._get_champion_name(champion_id)}"
        try:
            summoner = await self._lcu.get("/lol-summoner/v1/current-summoner") or {}
            summoner_id = summoner.get("summonerId")
            if not summoner_id:
                return
            path = f"/lol-item-sets/v1/item-sets/{summoner_id}/sets"
            document = await self._lcu.get(path) or {}
            await self._lcu.put(path, item_set_document(document, champion_id, title,
                                                        build.items))
            log.info("Applied item set %r", title)
        except (LCUError, KeyError, TypeError) as exc:
            log.warning("Applying item set failed: %s", exc)
```

In `src/laa/ui/worker.py`: change `from laa.runes.applier import RuneApplier` → `from laa.runes.applier import BuildApplier`, and `applier = RuneApplier(...)` → `applier = BuildApplier(...)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "feat: write meta item set on lock-in; rename RuneApplier -> BuildApplier"
```

---

### Task 5: UI — Builds tab + item-set checkbox

**Files:**
- Modify: `src/laa/ui/main_window.py`
- Test: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `Config.auto_items` (Task 1)
- Produces: `MainWindow._auto_items` (QCheckBox); the former "Runes" tab is now titled "Builds"

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_smoke.py`:

```python
def test_auto_items_checkbox_writes_config(qtbot, tmp_path):
    store = make_store(tmp_path)
    win = MainWindow(store, Bridge())
    qtbot.addWidget(win)
    assert win._auto_items.isChecked()  # default on
    win._auto_items.setChecked(False)
    assert store.get().auto_items is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest -q tests/test_ui_smoke.py -k auto_items`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_auto_items'`

- [ ] **Step 3: Implement**

In `src/laa/ui/main_window.py`:

1. Rename the tab: change `tabs.addTab(self._runes_tab(cfg), "Runes")` to
   `tabs.addTab(self._runes_tab(cfg), "Builds")`.

2. In `_runes_tab`, add the item checkbox between the meta-spells checkbox and the note. Replace this block:

```python
        meta_spells = QCheckBox("Also use meta summoner spells")
        meta_spells.setChecked(cfg.use_meta_spells)
        meta_spells.toggled.connect(lambda on: self._store.update(use_meta_spells=on))
        note = QLabel("Runes are written to a page named 'LAA: <Champion>'.\n"
                      "If the meta fetch fails, your current runes are left untouched.")
        note.setWordWrap(True)
        lay.addWidget(runes)
        lay.addWidget(meta_spells)
        lay.addWidget(note)
```

with:

```python
        meta_spells = QCheckBox("Also use meta summoner spells")
        meta_spells.setChecked(cfg.use_meta_spells)
        meta_spells.toggled.connect(lambda on: self._store.update(use_meta_spells=on))
        self._auto_items = QCheckBox("Auto-import meta item set")
        self._auto_items.setChecked(cfg.auto_items)
        self._auto_items.toggled.connect(lambda on: self._store.update(auto_items=on))
        note = QLabel("Runes and the item set are written to 'LAA: <Champion>'.\n"
                      "If the meta fetch fails, your current setup is left untouched.")
        note.setWordWrap(True)
        lay.addWidget(runes)
        lay.addWidget(meta_spells)
        lay.addWidget(self._auto_items)
        lay.addWidget(note)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: Builds tab with auto item-set checkbox"
```

---

## Post-plan verification

- **Docs:** add a bullet to the README feature list ("Auto item sets: on lock-in, a meta build from op.gg is written to a `LAA: <Champion>` item set in the shop; your own sets are untouched"), and a line to `docs/testing.md` ("lock a champion → an `LAA:` item set appears for it in the shop with sensible items; personal item sets untouched").
- **Live schema verification (required before release):** with the League client running, run the app and lock a champion in a real champ select, then open the shop and confirm the `LAA:` item set appears with sensible items and that personal sets are intact. To inspect the real document shape directly, write a tiny throwaway script (`scripts/probe_item_sets.py`, not committed) that reads the port/token via `laa.lcu.discovery.find_credentials()`, does basic-auth `GET /lol-summoner/v1/current-summoner` for the `summonerId`, then `GET /lol-item-sets/v1/item-sets/{summonerId}/sets`, and prints the JSON. If the client rejects the PUT, adjust the fields in `make_item_set` (the single construction site) until accepted — do not change the block/parse logic.
- Run superpowers:requesting-code-review before calling the feature done.
