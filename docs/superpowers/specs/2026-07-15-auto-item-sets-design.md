# Auto item sets / builds — Design

**Date:** 2026-07-15
**Status:** Approved by user (this session)
**Builds on:** the auto-rune feature — same op.gg data source, same lock-in trigger, same
silent-degrade policy. See [the original app design](2026-07-08-league-auto-accept-design.md).

## Goal

On champion lock-in, write a meta **item set** ("build") to the League client so it appears
in the in-game shop, using the item data already present in the op.gg response fetched for
runes. On by default, gated independently from runes.

## Behavior

- New config `auto_items: bool = True`, gated independently (like `auto_runes`).
- Triggered on lock-in, from the **same single op.gg fetch** already made for the rune page —
  no second network request.
- Produces one item set titled **`LAA: <Champion>`**, `associatedChampions: [<championId>]`
  so it auto-shows for that champion in the shop, with four blocks:
  - **Starters** — the highest-play entry of `starter_items` (an id list, e.g. Doran's + pots).
  - **Core** — the highest-play entry of `core_items` (the 3-item meta core).
  - **Boots** — the highest-play entry of `boots`.
  - **Situational** — the top ~6 individual items from `last_items` (already ranked by play),
    de-duplicated against items already shown in earlier blocks.
- **Never touches the user's own item sets.** The LCU stores all of a summoner's sets in one
  document that must be written back whole: read the document → drop any set whose `title`
  starts with `LAA:` → append the new set → PUT the whole document back.
- **Silent-degrade**, exactly like runes: any failure (op.gg fetch, summoner lookup, sets
  read/write) is logged and skipped; it never blocks or delays the pick.
- Only runs when a champion is locked (existing `on_locked` trigger) and `auto_items` is on
  and master pause is off.

## LCU endpoints

- `GET /lol-summoner/v1/current-summoner` → `summonerId` (item sets are keyed by summoner).
- `GET /lol-item-sets/v1/item-sets/{summonerId}/sets` → the full item-set **document**
  (`{"itemSets": [...], "timestamp": ..., ...}`).
- `PUT /lol-item-sets/v1/item-sets/{summonerId}/sets` → the modified document, whole.

**Item-set object shape (community-standard; verify live at implementation time):**

```json
{
  "title": "LAA: Ahri",
  "type": "custom",
  "map": "any",
  "mode": "any",
  "sortrank": 0,
  "startedFrom": "blank",
  "associatedChampions": [103],
  "associatedMaps": [],
  "preferredItemSlots": [],
  "blocks": [
    {"type": "Starters", "items": [{"id": "1056", "count": 1}]},
    {"type": "Core",     "items": [{"id": "3118", "count": 1}]},
    {"type": "Boots",    "items": [{"id": "3020", "count": 1}]},
    {"type": "Situational", "items": [{"id": "3157", "count": 1}]}
  ]
}
```

Item IDs in blocks are **strings**; op.gg gives ints, so convert. The exact required
top-level fields of the document and set object must be **verified against a live client**
during implementation (a probe/manual step), mirroring how the op.gg endpoint was de-risked —
the schema block above is the target, not an unverified assumption. If the live client rejects
the PUT, adjust the set-object fields (the one place they are constructed) until it accepts.

## Architecture (one fetch, clean boundaries)

Parallels the rune path: the **provider** parses op.gg data into typed values (Qt-free, no
I/O); the **applier** builds the LCU payload and performs the writes.

- **`src/laa/runes/provider.py`**
  - New frozen dataclass `ItemBuild(starter_ids: list[int], core_ids: list[int],
    boots_ids: list[int], situational_ids: list[int])`.
  - Extend `Build` with `items: ItemBuild | None`.
  - `parse_champion` also parses items from the same payload (highest-play entry for
    starter/core/boots; top-N `last_items` for situational, deduped). Missing/empty fields →
    empty lists; if there is nothing to build, `items` may be an `ItemBuild` with empty lists
    and the applier skips writing.
  - `SITUATIONAL_COUNT = 6` constant.
- **`src/laa/runes/applier.py`** — rename `RuneApplier` → **`BuildApplier`** (it now applies
  the whole meta build: runes, spells, and items). `apply(champion_id, role)`:
    1. one `provider.get_build(...)` fetch;
    2. if `auto_runes`: write rune page (unchanged);
    3. if `use_meta_spells`: write spells (unchanged);
    4. if `auto_items`: write item set (new).
  Each sub-action is independently gated and independently `try/except`-guarded (one failure
  never blocks the others). The pure LCU-payload builder
  `item_set_document(existing_doc, champion_id, name, item_build) -> dict` (drop old `LAA:`
  sets, append the new one) lives here or in a small helper and is unit-tested; the I/O
  (`GET current-summoner`, `GET`/`PUT` sets) is the applier's async method.
- **`src/laa/config.py`** — add `auto_items: bool = True`.
- **`src/laa/ui/worker.py`** — update the import/instantiation for the renamed `BuildApplier`
  (no behavioral change to wiring; `on_locked` still points at `applier.apply`).
- **`src/laa/ui/main_window.py`** — rename the **"Runes"** tab to **"Builds"** and add an
  **"Auto-import meta item set"** checkbox bound to `auto_items` (default checked), beside the
  existing auto-runes / meta-spells controls.

`laa/runes/` stays Qt-free. The rename is the only churn to existing tested code; existing
rune/spell tests keep passing (their behavior is unchanged), updated only for the class name.

## Error handling

- op.gg fetch already returns `None` on failure (existing) → nothing is applied.
- Item write path: if `current-summoner` or the sets `GET` fails, or the parsed item build is
  empty, log and skip — runes/spells still apply.
- The PUT is guarded; a rejection is logged (and, per the implementation-time live check, the
  set-object fields are corrected once). A later lock-in overwrites the `LAA:` set cleanly.
- Master pause / `auto_items` off → item write is not attempted.
- Item IDs are converted to strings defensively; a malformed op.gg entry yields an empty block
  rather than a crash.

## Testing

**Pure (`tests/test_provider.py`), no client:**
- `parse_champion` populates `ItemBuild` from a synthetic op.gg payload: highest-play entry
  chosen for starters/core/boots; top-`SITUATIONAL_COUNT` `last_items` for situational, deduped
  against earlier blocks; empty/missing fields → empty lists.

**Pure (`tests/test_applier.py`):**
- `item_set_document(...)`: given a document containing a user's own set and a stale `LAA:`
  set, the result **keeps the user set**, **drops the stale `LAA:` set**, and **appends** the
  new one with correct block types, **string** item IDs, `title == "LAA: <name>"`, and
  `associatedChampions == [championId]`.

**Applier I/O (`tests/test_applier.py`), FakeLCU:**
- With `auto_items` on and a lock-in: issues `GET current-summoner`, `GET sets`, then a `PUT`
  whose document contains exactly one `LAA:` set for the champion.
- `auto_items` off → no item-set calls (but runes still apply if enabled).
- Provider returns `None` or empty items → no `PUT`, no crash.
- A sets-read `LCUError` → logged, no `PUT`, runes/spells unaffected.

**Config (`tests/test_config.py`):** `auto_items` default `True` + roundtrip.

**UI (`tests/test_ui_smoke.py`):** the Builds tab's item checkbox is default-checked and writes
`auto_items`.

**Manual (documented):** in a live champ select, lock a champion and confirm an `LAA:` item set
appears for it in the shop with sensible items, and that pre-existing personal item sets are
untouched. Verify the live PUT schema here.

## Risks

- **LCU item-set schema drift / unverified fields.** Mitigated by isolating set-object
  construction in one pure function, a live-verification step at implementation time, and the
  silent-degrade policy (a rejected PUT never harms the pick).
- **op.gg item fields shifting.** Same mitigation as the rune path — one parse site, graceful
  empties, live shape already checked (2026-07-15).
