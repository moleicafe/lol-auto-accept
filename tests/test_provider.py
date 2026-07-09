import httpx

from laa.runes.provider import Build, OPGGProvider, parse_champion

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
