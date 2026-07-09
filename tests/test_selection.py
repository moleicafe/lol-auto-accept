from laa.core.selection import (assigned_position, choose_ban, choose_pick,
                                my_active_actions, my_completed_pick, ordered_spells)
from tests.helpers import action, make_session


def test_my_active_actions_filters_to_local_in_progress():
    s = make_session(cell=2, actions=[
        [action(1, 0, "ban", in_progress=True)],
        [action(2, 2, "ban", in_progress=True), action(3, 2, "pick")],
        [action(4, 2, "pick", completed=True, in_progress=True)],
    ])
    assert [a["id"] for a in my_active_actions(s)] == [2]


def test_choose_ban_skips_unbannable_and_already_banned():
    s = make_session(actions=[[action(1, 3, "ban", champion_id=157, completed=True)]])
    assert choose_ban([157, 238, 555], s, bannable={238, 555}) == 238


def test_choose_ban_none_when_list_exhausted():
    assert choose_ban([157], make_session(), bannable=set()) is None


def test_choose_pick_skips_banned_taken_unowned():
    s = make_session(actions=[
        [action(1, 3, "ban", champion_id=103, completed=True)],   # Ahri banned
        [action(2, 4, "pick", champion_id=1, completed=True)],    # Annie taken
    ])
    # 103 banned, 1 taken, 61 unowned (not pickable) -> 245
    assert choose_pick([103, 1, 61, 245], s, pickable={103, 1, 245}) == 245


def test_choose_pick_empty_list_returns_none():
    assert choose_pick([], make_session(), pickable={1}) is None


def test_assigned_position():
    assert assigned_position(make_session(position="jungle")) == "jungle"
    assert assigned_position(make_session(position="")) == ""


def test_my_completed_pick():
    s = make_session(actions=[[action(1, 0, "pick", champion_id=103, completed=True)]])
    assert my_completed_pick(s) == 103
    assert my_completed_pick(make_session()) is None


def test_ordered_spells_flash_preference():
    assert ordered_spells(4, 14, flash_on_f=True) == (14, 4)
    assert ordered_spells(4, 14, flash_on_f=False) == (4, 14)
    assert ordered_spells(14, 4, flash_on_f=False) == (4, 14)
    assert ordered_spells(12, 14, flash_on_f=True) == (12, 14)  # no flash: unchanged
