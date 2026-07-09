from laa.config import Config
from laa.core.engine import Engine
from laa.lcu import events
from tests.helpers import FakeLCU, action, make_session

PHASE = ("GET", "/lol-gameflow/v1/gameflow-phase")
CATALOG = ("GET", "/lol-game-data/assets/v1/champion-summary.json")


class StubApplier:
    def __init__(self):
        self.applied = []

    async def apply(self, cid, role):
        self.applied.append((cid, role))


class StubCatalog:
    def __init__(self):
        self.refreshes = 0

    async def refresh(self):
        self.refreshes += 1

    def all(self):
        return {}


def make_engine(lcu=None, cfg=None):
    lcu = lcu or FakeLCU({PHASE: "None"})
    applier = StubApplier()
    catalog = StubCatalog()
    statuses = []
    eng = Engine(lcu, lambda: cfg or Config(auto_runes=True), catalog, applier,
                 notify=statuses.append)
    return eng, lcu, applier, catalog, statuses


async def test_connected_syncs_catalog_phase_and_status():
    lcu = FakeLCU({PHASE: "Lobby"})
    eng, _, _, catalog, statuses = make_engine(lcu)
    await eng.on_event(events.Connected())
    assert catalog.refreshes == 1
    assert eng.phase == "Lobby"
    assert statuses[-1] == "In lobby"


async def test_connected_status_fires_even_when_catalog_refresh_fails():
    lcu = FakeLCU({PHASE: "Lobby"})
    eng, _, _, catalog, statuses = make_engine(lcu)

    async def boom():
        raise RuntimeError("kaput")

    catalog.refresh = boom
    await eng.on_event(events.Connected())
    assert "Connected" in statuses


async def test_ready_check_routed_and_reset_on_phase_change():
    eng, lcu, _, _, _ = make_engine()
    await eng.on_event(events.GameflowPhase(phase="ReadyCheck"))
    rc = events.ReadyCheckUpdate(state="InProgress", player_response="None")
    await eng.on_event(rc)
    await eng.on_event(rc)
    accepts = lcu.sent("POST", "/lol-matchmaking/v1/ready-check/accept")
    assert len(accepts) == 1
    # new queue -> new ready check accepted again
    await eng.on_event(events.GameflowPhase(phase="Matchmaking"))
    await eng.on_event(events.GameflowPhase(phase="ReadyCheck"))
    await eng.on_event(rc)
    assert len(lcu.sent("POST", "/lol-matchmaking/v1/ready-check/accept")) == 2


async def test_lock_in_triggers_rune_apply_once_and_resets_next_champ_select():
    eng, lcu, applier, _, _ = make_engine()
    s = make_session(position="middle",
                     actions=[[action(7, 0, "pick", champion_id=103, completed=True)]])
    await eng.on_event(events.GameflowPhase(phase="ChampSelect"))
    await eng.on_event(events.ChampSelectUpdate(session=s))
    await eng.on_event(events.ChampSelectUpdate(session=s))
    assert applier.applied == [(103, "middle")]
    # leave and re-enter champ select -> fires again
    await eng.on_event(events.GameflowPhase(phase="InProgress"))
    await eng.on_event(events.GameflowPhase(phase="ChampSelect"))
    await eng.on_event(events.ChampSelectUpdate(session=s))
    assert applier.applied == [(103, "middle"), (103, "middle")]


async def test_engine_never_raises():
    eng, lcu, _, catalog, _ = make_engine()

    async def boom():
        raise RuntimeError("kaput")

    catalog.refresh = boom
    await eng.on_event(events.Connected())  # must not raise
    assert eng.phase in ("", "None", "Lobby")


async def test_disconnected_status():
    eng, _, _, _, statuses = make_engine()
    await eng.on_event(events.Disconnected())
    assert statuses[-1] == "Waiting for League client"


async def test_none_phase_notifies_friendly_label_not_literal_none():
    eng, _, _, _, statuses = make_engine()
    await eng.on_event(events.GameflowPhase(phase="None"))
    assert eng.phase == "None"          # raw phase preserved for reset logic
    assert statuses[-1] == "In client"  # but the notified status is friendly
