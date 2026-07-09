from laa.lcu.catalog import ChampionCatalog
from tests.helpers import FakeLCU

SUMMARY = ("GET", "/lol-game-data/assets/v1/champion-summary.json")


async def test_refresh_and_lookup():
    lcu = FakeLCU({SUMMARY: [
        {"id": -1, "name": "None"}, {"id": 103, "name": "Ahri"}, {"id": 1, "name": "Annie"},
    ]})
    cat = ChampionCatalog(lcu)
    assert cat.name(103) == "#103"  # before refresh: placeholder
    await cat.refresh()
    assert cat.name(103) == "Ahri"
    assert cat.all() == {103: "Ahri", 1: "Annie"}  # id -1 filtered out
