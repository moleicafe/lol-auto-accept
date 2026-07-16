from laa.config import Config
from laa.runes.applier import BuildApplier, item_set_document, make_item_set
from laa.runes.provider import Build, ItemBuild
from tests.helpers import FakeLCU

ITEMS = ItemBuild(starter_ids=[1054], core_ids=[3118, 4645, 3157],
                  boots_ids=[3020], situational_ids=[3089, 3135])


def test_make_item_set_shape():
    s = make_item_set(103, "LAA: Ahri", ITEMS)
    assert s["title"] == "LAA: Ahri"
    assert s["associatedChampions"] == [103]
    assert s["type"] == "custom"
    assert [b["type"] for b in s["blocks"]] == ["Starters", "Core", "Boots", "Situational"]
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
    assert "My build" in titles
    assert "LAA: Yasuo" not in titles
    assert titles.count("LAA: Ahri") == 1
    assert doc["timestamp"] == 123

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
    return BuildApplier(lcu, StubProvider(build), lambda: cfg, lambda cid: "Ahri")


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
    applier = make_applier(lcu, auto_runes=False, use_meta_spells=False, auto_items=False)
    await applier.apply(103, "middle")
    assert applier._provider.requests == []


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
    assert titles == ["My build", "LAA: Ahri"]


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


def test_core_block_title_formats():
    from laa.runes.applier import core_block_title
    assert core_block_title(["Q", "W", "E"], ["W", "Q", "E", "Q"]) == \
        "Core — max Q>W>E (start W-Q-E-Q)"
    assert core_block_title(["Q", "W", "E"], []) == "Core — max Q>W>E"
    assert core_block_title([], []) == "Core"


async def test_item_set_core_title_includes_skill_order():
    build = Build(primary_style_id=8100, sub_style_id=8000,
                  perk_ids=BUILD.perk_ids, spell_ids=(14, 4), items=ITEMS)
    object.__setattr__(build, "skill_max", ["Q", "W", "E"])
    object.__setattr__(build, "skill_start", ["W", "Q", "E", "Q"])
    lcu = FakeLCU({PAGES: [], SUMMONER: {"summonerId": 55}, SETS: {"itemSets": []}})
    await make_applier(lcu, build=build, auto_runes=False).apply(103, "middle")
    doc = lcu.sent("PUT", "/lol-item-sets/v1/item-sets/55/sets")[0][2]
    core = next(b for b in doc["itemSets"][0]["blocks"] if b["type"].startswith("Core"))
    assert core["type"] == "Core — max Q>W>E (start W-Q-E-Q)"
