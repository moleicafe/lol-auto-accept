from laa.config import Config
from laa.core.ready_check import ReadyCheckAutomation
from laa.lcu.events import ReadyCheckUpdate
from tests.helpers import FakeLCU

ACCEPT = ("POST", "/lol-matchmaking/v1/ready-check/accept")
IN_PROGRESS = ReadyCheckUpdate(state="InProgress", player_response="None")


async def test_accepts_when_in_progress():
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config())
    await auto.on_update(IN_PROGRESS)
    assert [(c[0], c[1]) for c in lcu.calls] == [ACCEPT]


async def test_accepts_only_once_until_reset():
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config())
    await auto.on_update(IN_PROGRESS)
    await auto.on_update(IN_PROGRESS)
    assert len(lcu.calls) == 1
    auto.reset()
    await auto.on_update(IN_PROGRESS)
    assert len(lcu.calls) == 2


async def test_no_accept_when_disabled_or_paused():
    for cfg in (Config(auto_accept=False), Config(master_paused=True)):
        lcu = FakeLCU()
        await ReadyCheckAutomation(lcu, lambda c=cfg: c).on_update(IN_PROGRESS)
        assert lcu.calls == []


async def test_no_accept_when_already_responded():
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config())
    await auto.on_update(ReadyCheckUpdate(state="InProgress", player_response="Accepted"))
    assert lcu.calls == []


async def test_delay_is_honored(monkeypatch):
    import laa.core.ready_check as rc
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(rc.asyncio, "sleep", fake_sleep)
    lcu = FakeLCU()
    auto = ReadyCheckAutomation(lcu, lambda: Config(accept_delay_s=3.0))
    await auto.on_update(IN_PROGRESS)
    assert slept == [3.0]
    assert len(lcu.calls) == 1
