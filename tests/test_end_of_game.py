from laa.config import Config
from laa.core.end_of_game import EndOfGameAutomation
from laa.lcu.connector import LCUError
from tests.helpers import FakeLCU

BALLOT = ("GET", "/lol-honor-v2/v1/ballot")
HONOR = ("POST", "/lol-honor-v2/v1/honor-player")
PLAY_AGAIN = ("POST", "/lol-lobby/v2/play-again")

ELIGIBLE = {"eligibleAllies": [
    {"summonerId": 11, "puuid": "p11"},
    {"summonerId": 22, "puuid": "p22"},
]}


def make_auto(lcu, chooser=None, **cfg_kw):
    cfg = Config(**cfg_kw)
    return EndOfGameAutomation(lcu, lambda: cfg, choose=chooser or (lambda seq: seq[0]))


async def test_honors_first_eligible_ally_once():
    lcu = FakeLCU({BALLOT: ELIGIBLE})
    auto = make_auto(lcu)
    await auto.on_phase("PreEndOfGame")
    await auto.on_phase("PreEndOfGame")  # second event same game -> no double honor
    honors = lcu.sent("POST", "/lol-honor-v2/v1/honor-player")
    assert len(honors) == 1
    assert honors[0][2]["summonerId"] == 11
    assert honors[0][2]["puuid"] == "p11"


async def test_honor_respects_toggle_and_pause():
    for cfg_kw in ({"auto_honor": False}, {"master_paused": True}):
        lcu = FakeLCU({BALLOT: ELIGIBLE})
        await make_auto(lcu, **cfg_kw).on_phase("PreEndOfGame")
        assert lcu.sent("POST", "/lol-honor-v2/v1/honor-player") == []


async def test_honor_silent_when_ballot_empty_or_errors():
    lcu = FakeLCU({BALLOT: {"eligibleAllies": []}})
    await make_auto(lcu).on_phase("PreEndOfGame")
    assert lcu.sent("POST", "/lol-honor-v2/v1/honor-player") == []

    lcu2 = FakeLCU()
    lcu2.errors[BALLOT] = LCUError("500")
    await make_auto(lcu2).on_phase("PreEndOfGame")  # must not raise
    assert lcu2.sent("POST", "/lol-honor-v2/v1/honor-player") == []


async def test_play_again_only_when_enabled_and_once():
    lcu = FakeLCU()
    auto = make_auto(lcu, auto_play_again=True)
    await auto.on_phase("EndOfGame")
    await auto.on_phase("EndOfGame")
    assert len(lcu.sent("POST", "/lol-lobby/v2/play-again")) == 1

    lcu2 = FakeLCU()
    await make_auto(lcu2).on_phase("EndOfGame")  # default off
    assert lcu2.sent("POST", "/lol-lobby/v2/play-again") == []


async def test_reset_rearms_for_next_game():
    lcu = FakeLCU({BALLOT: ELIGIBLE})
    auto = make_auto(lcu, auto_play_again=True)
    await auto.on_phase("PreEndOfGame")
    await auto.on_phase("EndOfGame")
    auto.reset()
    await auto.on_phase("PreEndOfGame")
    await auto.on_phase("EndOfGame")
    assert len(lcu.sent("POST", "/lol-honor-v2/v1/honor-player")) == 2
    assert len(lcu.sent("POST", "/lol-lobby/v2/play-again")) == 2


async def test_other_phases_do_nothing():
    lcu = FakeLCU({BALLOT: ELIGIBLE})
    auto = make_auto(lcu, auto_play_again=True)
    for phase in ("Lobby", "ChampSelect", "InProgress", "None"):
        await auto.on_phase(phase)
    assert lcu.calls == []
