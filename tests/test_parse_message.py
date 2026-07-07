import json

from laa.lcu import events
from laa.lcu.connector import _parse_message


def wrap(uri, data, event_type="Update"):
    return json.dumps([8, "OnJsonApiEvent", {"uri": uri, "eventType": event_type, "data": data}])


def test_gameflow_phase():
    ev = _parse_message(wrap("/lol-gameflow/v1/gameflow-phase", "ReadyCheck"))
    assert ev == events.GameflowPhase(phase="ReadyCheck")


def test_ready_check():
    ev = _parse_message(wrap("/lol-matchmaking/v1/ready-check", {"state": "InProgress", "playerResponse": "None"}))
    assert ev == events.ReadyCheckUpdate(state="InProgress", player_response="None")


def test_champ_select():
    ev = _parse_message(wrap("/lol-champ-select/v1/session", {"localPlayerCellId": 0}))
    assert ev == events.ChampSelectUpdate(session={"localPlayerCellId": 0})


def test_irrelevant_uri_returns_none():
    assert _parse_message(wrap("/lol-lobby/v2/lobby", {})) is None


def test_garbage_returns_none():
    assert _parse_message("not json") is None
    assert _parse_message(json.dumps([5, "OnJsonApiEvent"])) is None
    assert _parse_message(json.dumps({"uri": "x"})) is None


def test_ready_check_delete_event_with_null_data_returns_none():
    assert _parse_message(wrap("/lol-matchmaking/v1/ready-check", None)) is None


def test_ready_check_delete_event_with_populated_data_returns_none():
    raw = wrap(
        "/lol-matchmaking/v1/ready-check",
        {"state": "InProgress", "playerResponse": "None"},
        event_type="Delete",
    )
    assert _parse_message(raw) is None
