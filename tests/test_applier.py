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
