from laa.config import Config
from laa.core.scout import LobbyScout
from laa.lcu.connector import LCUError
from tests.helpers import FakeLCU, make_session

REGION = ("GET", "/riotclient/region-locale")


def lobby_session():
    s = make_session(cell=0)
    s["myTeam"] = [
        {"cellId": 0, "summonerId": 10},          # local player -> excluded
        {"cellId": 1, "summonerId": 11},
        {"cellId": 2, "summonerId": 12},
        {"cellId": 3, "summonerId": 0},           # anonymized -> skipped
    ]
    return s


def scout_with(lcu, **cfg_kw):
    return LobbyScout(lcu, lambda: Config(**cfg_kw))


def make_lcu():
    return FakeLCU({
        REGION: {"region": "EUW", "locale": "en_GB"},
        ("GET", "/lol-summoner/v2/summoners/11"): {"gameName": "Faker Fan", "tagLine": "EUW"},
        ("GET", "/lol-summoner/v2/summoners/12"): {"gameName": "Molei", "tagLine": "0001"},
    })


async def test_build_url_excludes_local_encodes_and_uses_region():
    scout = scout_with(make_lcu())
    scout.update_session(lobby_session())
    url = await scout.build_url()
    assert url == ("https://op.gg/multisearch/euw"
                   "?summoners=Faker%20Fan%23EUW%2CMolei%230001")


async def test_build_url_region_fallback_na():
    lcu = make_lcu()
    lcu.errors[REGION] = LCUError("500")
    scout = scout_with(lcu)
    scout.update_session(lobby_session())
    url = await scout.build_url()
    assert url.startswith("https://op.gg/multisearch/na?")


async def test_build_url_none_without_session_or_allies():
    scout = scout_with(make_lcu())
    assert await scout.build_url() is None          # no session yet
    empty = make_session(cell=0)
    empty["myTeam"] = [{"cellId": 0, "summonerId": 10}]
    scout.update_session(empty)
    assert await scout.build_url() is None          # no allies


async def test_build_url_skips_failed_lookups():
    lcu = make_lcu()
    lcu.errors[("GET", "/lol-summoner/v2/summoners/11")] = LCUError("404")
    scout = scout_with(lcu)
    scout.update_session(lobby_session())
    url = await scout.build_url()
    assert "Molei%230001" in url and "Faker" not in url


async def test_maybe_auto_url_fires_once_and_respects_config():
    scout = scout_with(make_lcu(), multisearch_auto=True)
    first = await scout.maybe_auto_url(lobby_session())
    second = await scout.maybe_auto_url(lobby_session())
    assert first is not None and second is None      # once per champ select
    scout.reset()
    assert await scout.maybe_auto_url(lobby_session()) is not None

    off = scout_with(make_lcu())                     # multisearch_auto defaults off
    assert await off.maybe_auto_url(lobby_session()) is None
