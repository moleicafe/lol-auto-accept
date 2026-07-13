import asyncio

from laa.config import Config
from laa.core.champ_select import ChampSelectAutomation
from tests.helpers import FakeLCU, action, make_session

PICKABLE = ("GET", "/lol-champ-select/v1/pickable-champion-ids")
BANNABLE = ("GET", "/lol-champ-select/v1/bannable-champion-ids")
CONVOS = ("GET", "/lol-chat/v1/conversations")
SESSION = ("GET", "/lol-champ-select/v1/session")


def lcu_with(pickable=(103, 1, 245), bannable=(157, 238)):
    return FakeLCU({
        PICKABLE: list(pickable),
        BANNABLE: list(bannable),
        CONVOS: [{"id": "abc@champ-select.pvp.net", "type": "championSelect"}],
    })


def cfg(**kw):
    base = dict(pick_ids=[103, 245], ban_ids=[157, 238], set_spells=False,
                lobby_message="", instalock=False, auto_runes=False)
    base.update(kw)
    return Config(**base)


async def test_ban_declared_and_completed():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    await auto.on_session(make_session(actions=[[action(5, 0, "ban", in_progress=True)]]))
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5")
    assert patches == [("PATCH", "/lol-champ-select/v1/session/actions/5",
                        {"championId": 157, "completed": True})]


async def test_pick_hovers_without_instalock():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    await auto.on_session(make_session(actions=[[action(7, 0, "pick", in_progress=True)]]))
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")
    assert patches == [("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 103})]


async def test_pick_locks_with_instalock():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg(instalock=True))
    await auto.on_session(make_session(actions=[[action(7, 0, "pick", in_progress=True)]]))
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")
    assert patches[-1][2] == {"championId": 103, "completed": True}


async def test_pick_falls_back_when_first_choice_banned():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[
        [action(1, 3, "ban", champion_id=103, completed=True)],
        [action(7, 0, "pick", in_progress=True)],
    ])
    await auto.on_session(s)
    patches = lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")
    assert patches == [("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 245})]


async def test_hover_not_repeated_for_same_champion():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[[action(7, 0, "pick", in_progress=True)]])
    await auto.on_session(s)
    await auto.on_session(s)
    assert len(lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")) == 1


async def test_spells_applied_once_with_flash_ordering():
    lcu = lcu_with()
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(set_spells=True, spell1_id=4, spell2_id=14, flash_on_f=True))
    await auto.on_session(make_session())
    await auto.on_session(make_session())
    sel = lcu.sent("PATCH", "/lol-champ-select/v1/session/my-selection")
    assert sel == [("PATCH", "/lol-champ-select/v1/session/my-selection",
                    {"spell1Id": 14, "spell2Id": 4})]


async def test_chat_message_sent_once():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg(lobby_message="glhf"))
    await auto.on_session(make_session())
    await auto.on_session(make_session())
    msgs = lcu.sent("POST", "/lol-chat/v1/conversations/abc@champ-select.pvp.net/messages")
    assert msgs == [("POST", "/lol-chat/v1/conversations/abc@champ-select.pvp.net/messages",
                     {"body": "glhf", "type": "chat"})]


async def test_on_locked_fires_once_with_position():
    lcu = lcu_with()
    locked: list = []

    async def on_locked(cid, pos):
        locked.append((cid, pos))

    auto = ChampSelectAutomation(lcu, lambda: cfg(), on_locked=on_locked)
    s = make_session(position="jungle",
                     actions=[[action(7, 0, "pick", champion_id=103, completed=True)]])
    await auto.on_session(s)
    await auto.on_session(s)
    assert locked == [(103, "jungle")]


async def test_pick_refetches_when_pickable_initially_empty():
    lcu = lcu_with(pickable=[])
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[[action(7, 0, "pick", in_progress=True)]])
    await auto.on_session(s)
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7") == []
    lcu.responses[PICKABLE] = [103, 245]
    await auto.on_session(s)
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7") == [
        ("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 103})]


async def test_ban_attempted_directly_when_bannable_endpoint_empty():
    # An empty (or useless) bannable list no longer blocks banning: the client
    # itself validates, so we attempt the top list choice directly.
    lcu = lcu_with(bannable=[])
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[[action(5, 0, "ban", in_progress=True)]])
    await auto.on_session(s)
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5") == [
        ("PATCH", "/lol-champ-select/v1/session/actions/5",
         {"championId": 157, "completed": True})]


async def test_paused_does_nothing():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg(master_paused=True, lobby_message="hi",
                                                  set_spells=True))
    await auto.on_session(make_session(actions=[[action(7, 0, "pick", in_progress=True)]]))
    assert lcu.calls == []


def hovered_session(cid=103, ms=1000):
    return make_session(actions=[[action(7, 0, "pick", champion_id=cid, in_progress=True)]],
                        time_left_ms=ms)


async def test_safety_lock_locks_hovered_champ():
    s = hovered_session()
    lcu = FakeLCU({SESSION: s, PICKABLE: [103, 245]})
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[]))
    await auto.on_session(s)          # delay = 1.0 - 1.0 = 0
    await auto._safety_task           # run the scheduled lock
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")[-1] == (
        "PATCH", "/lol-champ-select/v1/session/actions/7",
        {"championId": 103, "completed": True})


async def test_safety_lock_falls_back_to_pick_list_when_no_hover():
    s = make_session(actions=[[action(7, 0, "pick", in_progress=True)]], time_left_ms=1000)
    lcu = FakeLCU({SESSION: s, PICKABLE: [245]})
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[245]))
    await auto.on_session(s)
    await auto._safety_task
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7")[-1] == (
        "PATCH", "/lol-champ-select/v1/session/actions/7",
        {"championId": 245, "completed": True})


async def test_no_safety_task_when_instalock():
    s = hovered_session()
    auto = ChampSelectAutomation(
        FakeLCU({SESSION: s, PICKABLE: [103]}),
        lambda: cfg(safety_lock=True, instalock=True, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_no_safety_task_when_safety_disabled():
    s = hovered_session()
    auto = ChampSelectAutomation(FakeLCU({SESSION: s}),
                                 lambda: cfg(safety_lock=False, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_no_safety_task_when_not_my_pick_turn():
    s = make_session(time_left_ms=1000)  # no actions -> not my turn
    auto = ChampSelectAutomation(FakeLCU({SESSION: s}),
                                 lambda: cfg(safety_lock=True, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_no_safety_task_when_timer_infinite():
    s = make_session(actions=[[action(7, 0, "pick", champion_id=103, in_progress=True)]],
                     time_left_ms=1000, timer_infinite=True)
    auto = ChampSelectAutomation(FakeLCU({SESSION: s}),
                                 lambda: cfg(safety_lock=True, pick_ids=[]))
    await auto.on_session(s)
    assert auto._safety_task is None


async def test_safety_lock_skips_if_already_locked_at_fire_time():
    arming = hovered_session()  # in progress when armed
    fired = make_session(  # completed by the time the task fires
        actions=[[action(7, 0, "pick", champion_id=103, completed=True)]], time_left_ms=1000)
    lcu = FakeLCU({SESSION: fired, PICKABLE: [103]})
    auto = ChampSelectAutomation(
        lcu, lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[]))
    await auto.on_session(arming)
    await auto._safety_task
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/7") == []


async def test_reset_cancels_pending_safety_task():
    s = make_session(actions=[[action(7, 0, "pick", champion_id=103, in_progress=True)]],
                     time_left_ms=30000)  # 30s -> long delay, task stays pending
    auto = ChampSelectAutomation(
        FakeLCU({SESSION: s, PICKABLE: [103]}),
        lambda: cfg(safety_lock=True, safety_lock_buffer_s=1.0, pick_ids=[]))
    await auto.on_session(s)
    task = auto._safety_task
    assert task is not None and not task.done()
    auto.reset()
    await asyncio.sleep(0)  # let the cancellation propagate
    assert task.cancelled()
    assert auto._safety_task is None


async def test_no_action_processing_during_planning_phase():
    # Ranked pick-intent phase: ban action is already "in progress" but bans
    # cannot be completed and availability endpoints return placeholder data.
    s = make_session(actions=[[action(5, 0, "ban", in_progress=True)]], phase="PLANNING")
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    await auto.on_session(s)
    assert lcu.sent("GET", "/lol-champ-select/v1/bannable-champion-ids") == []
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5") == []


async def test_ban_works_after_planning_does_not_poison_cache():
    planning = make_session(actions=[[action(5, 0, "ban", in_progress=True)]], phase="PLANNING")
    banning = make_session(actions=[[action(5, 0, "ban", in_progress=True)]])  # BAN_PICK
    lcu = lcu_with()  # bannable = {157, 238}
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    await auto.on_session(planning)  # must fetch nothing, cache nothing
    await auto.on_session(banning)
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5")[-1] == (
        "PATCH", "/lol-champ-select/v1/session/actions/5",
        {"championId": 157, "completed": True})


async def test_ban_attempted_even_when_bannable_endpoint_returns_garbage():
    # Live-captured failure: bannable-champion-ids returned a bogus 1-champion
    # list in ranked. The client itself validates bans, so we attempt anyway.
    lcu = lcu_with(bannable=[999])
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    await auto.on_session(make_session(actions=[[action(5, 0, "ban", in_progress=True)]]))
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5")[-1] == (
        "PATCH", "/lol-champ-select/v1/session/actions/5",
        {"championId": 157, "completed": True})


async def test_ban_falls_to_next_choice_when_lcu_rejects_first():
    from laa.lcu.connector import LCUError
    lcu = lcu_with(bannable=[999])
    lcu.errors[("PATCH", "/lol-champ-select/v1/session/actions/5")] = LCUError("400: invalid")
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[[action(5, 0, "ban", in_progress=True)]])
    await auto.on_session(s)          # tries 157 -> LCU rejects
    del lcu.errors[("PATCH", "/lol-champ-select/v1/session/actions/5")]
    await auto.on_session(s)          # next update: must move on to 238
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5")[-1][2] == {
        "championId": 238, "completed": True}


async def test_ban_still_skips_champs_already_banned_in_session():
    lcu = lcu_with(bannable=[999])    # endpoint garbage; session is the truth
    auto = ChampSelectAutomation(lcu, lambda: cfg())
    s = make_session(actions=[
        [action(1, 3, "ban", champion_id=157, completed=True)],   # 157 already banned
        [action(5, 0, "ban", in_progress=True)],
    ])
    await auto.on_session(s)
    assert lcu.sent("PATCH", "/lol-champ-select/v1/session/actions/5")[-1][2] == {
        "championId": 238, "completed": True}
