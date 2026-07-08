import json
from pathlib import Path

from laa.config import Config
from laa.ui.store import ConfigStore


def test_update_replaces_and_persists(tmp_path: Path):
    path = tmp_path / "config.json"
    store = ConfigStore(Config(), path)
    before = store.get()
    after = store.update(instalock=True, pick_ids=[103])
    assert after.instalock is True and after.pick_ids == [103]
    assert before.instalock is False          # old snapshot untouched
    assert store.get() is after               # atomic reference swap
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["instalock"] is True
