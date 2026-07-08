from laa.config import Config
from laa.core.champ_select import ChampSelectAutomation
from tests.helpers import FakeLCU, action, make_session

PICKABLE = ("GET", "/lol-champ-select/v1/pickable-champion-ids")
BANNABLE = ("GET", "/lol-champ-select/v1/bannable-champion-ids")
CONVOS = ("GET", "/lol-chat/v1/conversations")


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


async def test_paused_does_nothing():
    lcu = lcu_with()
    auto = ChampSelectAutomation(lcu, lambda: cfg(master_paused=True, lobby_message="hi",
                                                  set_spells=True))
    await auto.on_session(make_session(actions=[[action(7, 0, "pick", in_progress=True)]]))
    assert lcu.calls == []
