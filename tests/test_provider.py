import httpx

from laa.runes.provider import (Build, ItemBuild, OPGGProvider, SITUATIONAL_COUNT,
                                parse_champion, parse_item_build)


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
    build = parse_champion(data)
    assert build is not None
    assert build.items == ItemBuild([1054], [3118, 4645, 3157], [3020],
                                    [3089, 3135, 3165, 3116, 3102, 3040])

# One real op.gg "runes" entry (Ahri mid, 2026-07-08) plus a lower-play decoy.
RUNE_TOP = {
    "primary_page_id": 8100, "primary_rune_ids": [8112, 8139, 8140, 8106],
    "secondary_page_id": 8200, "secondary_rune_ids": [8210, 8226],
    "stat_mod_ids": [5005, 5008, 5001], "play": 9000, "win": 4500,
}
RUNE_DECOY = {
    "primary_page_id": 8000, "primary_rune_ids": [8005, 9111, 9104, 8014],
    "secondary_page_id": 8400, "secondary_rune_ids": [8444, 8453],
    "stat_mod_ids": [5005, 5008, 5002], "play": 100, "win": 40,
}
EXPECTED_PERKS = [8112, 8139, 8140, 8106, 8210, 8226, 5005, 5008, 5001]


def make_data(positions=("MID",)):
    return {
        "summary": {"positions": [{"name": n} for n in positions]},
        "runes": [RUNE_DECOY, RUNE_TOP],                       # unordered on purpose
        "summoner_spells": [{"ids": [4, 12], "play": 50},
                            {"ids": [4, 14], "play": 9000}],   # highest play wins
    }


def test_parse_champion_picks_most_played_rune_and_spells():
    build = parse_champion(make_data())
    assert build == Build(primary_style_id=8100, sub_style_id=8200,
                          perk_ids=EXPECTED_PERKS, spell_ids=(4, 14))


def test_parse_champion_garbage_returns_none():
    assert parse_champion({}) is None
    assert parse_champion({"runes": [], "summoner_spells": []}) is None
    assert parse_champion({"runes": [{"primary_page_id": 8100}],
                           "summoner_spells": []}) is None  # missing rune fields


async def test_get_build_maps_lcu_position_and_parses():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "lol-api-champion.op.gg"
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": make_data()})

    provider = OPGGProvider(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    build = await provider.get_build(103, "middle")
    assert seen["path"] == "/api/global/champions/ranked/103/mid"   # middle -> mid
    assert build is not None and build.spell_ids == (4, 14)


async def test_get_build_unassigned_resolves_primary_position():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        # first call (probe) reports the champion's primary lane as SUPPORT
        return httpx.Response(200, json={"data": make_data(positions=("SUPPORT",))})

    provider = OPGGProvider(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    build = await provider.get_build(412, "")           # unassigned
    assert build is not None
    assert calls[-1] == "/api/global/champions/ranked/412/support"  # resolved to support


async def test_get_build_returns_none_on_http_error():
    provider = OPGGProvider(http=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert await provider.get_build(103, "middle") is None
