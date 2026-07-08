import httpx

from laa.runes.provider import Build, UGGProvider, parse_overview, to_ugg_version

PERKS = [8112, 8143, 8138, 8135, 8009, 9105]
SHARDS = ["5008", "5008", "5002"]


def make_overview(role_id="5", matches=1000):
    stats = [
        [matches, 600, 8100, 8000, list(PERKS)],   # [0] perks: matches, wins, primary, sub, ids
        [matches, 600, [4, 14]],                    # [1] summoner spells
        None, None, None, None, None, None,         # [2..7] unused by us
        [matches, 600, list(SHARDS)],               # [8] stat shards
    ]
    return {"12": {"10": {role_id: [stats]}}}


def test_to_ugg_version():
    assert to_ugg_version("15.13.1") == "15_13"
    assert to_ugg_version("14.1.5") == "14_1"


def test_parse_overview_exact_role():
    build = parse_overview(make_overview(role_id="5"), "middle")
    assert build == Build(primary_style_id=8100, sub_style_id=8000,
                          perk_ids=PERKS + [5008, 5008, 5002], spell_ids=(4, 14))


def test_parse_overview_falls_back_to_most_played_role():
    data = {"12": {"10": {
        "1": make_overview("1")["12"]["10"]["1"],
    }}}
    data["12"]["10"]["1"][0][0][0] = 5000  # jungle has the most games
    build = parse_overview(data, "middle")  # middle absent -> jungle
    assert build is not None
    assert build.primary_style_id == 8100


def test_parse_overview_garbage_returns_none():
    assert parse_overview({}, "middle") is None
    assert parse_overview({"12": {"10": {}}}, "middle") is None
    assert parse_overview({"12": {"10": {"5": [[]]}}}, "middle") is None


async def test_get_build_via_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if "ddragon" in request.url.host:
            return httpx.Response(200, json=["15.13.1", "15.12.1"])
        assert "stats2.u.gg" in request.url.host
        assert "/overview/15_13/ranked_solo_5x5/103/" in request.url.path
        return httpx.Response(200, json=make_overview())

    provider = UGGProvider(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    build = await provider.get_build(103, "middle")
    assert build is not None and build.spell_ids == (4, 14)


async def test_get_build_returns_none_on_http_error():
    provider = UGGProvider(http=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert await provider.get_build(103, "middle") is None
