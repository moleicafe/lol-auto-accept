from pathlib import Path

from laa.config import Config, load, save


def test_defaults_when_file_missing(tmp_path: Path):
    cfg = load(tmp_path / "nope.json")
    assert cfg.auto_accept is True
    assert cfg.pick_ids == []
    assert cfg.instalock is False
    assert cfg.auto_runes is True


def test_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Config(pick_ids=[103, 1], ban_ids=[157], lobby_message="glhf", accept_delay_s=2.0)
    save(cfg, path)
    loaded = load(path)
    assert loaded == cfg


def test_corrupt_file_returns_defaults(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{not json!!", encoding="utf-8")
    assert load(path) == Config()


def test_unknown_keys_ignored(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text('{"auto_accept": false, "some_future_key": 1}', encoding="utf-8")
    cfg = load(path)
    assert cfg.auto_accept is False


def test_non_dict_json_returns_defaults(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load(path) == Config()
