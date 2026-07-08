from pathlib import Path

from laa.config import Config
from laa.ui.bridge import Bridge
from laa.ui.main_window import ChampListEditor, MainWindow
from laa.ui.store import ConfigStore


def make_store(tmp_path: Path, **kw) -> ConfigStore:
    return ConfigStore(Config(**kw), tmp_path / "config.json")


def test_window_constructs_and_reacts_to_signals(qtbot, tmp_path):
    store = make_store(tmp_path, pick_ids=[103])
    bridge = Bridge()
    win = MainWindow(store, bridge)
    qtbot.addWidget(win)
    assert win.windowTitle() == "League Auto Accept"
    bridge.status.emit("Connected")
    assert win._status.text() == "Connected"
    bridge.catalog_ready.emit({103: "Ahri", 1: "Annie"})
    assert win._picks._list.item(0).text() == "Ahri"
    bridge.log_line.emit("hello")
    assert "hello" in win._log.toPlainText()


def test_pause_button_writes_config(qtbot, tmp_path):
    store = make_store(tmp_path)
    win = MainWindow(store, Bridge())
    qtbot.addWidget(win)
    win._pause.setChecked(True)
    assert store.get().master_paused is True


def test_champ_list_editor_add_remove_move(qtbot):
    ed = ChampListEditor("Picks")
    qtbot.addWidget(ed)
    ed.set_catalog({103: "Ahri", 1: "Annie", 61: "Orianna"})
    changes: list = []
    ed.changed.connect(changes.append)
    ed._combo.setCurrentIndex(ed._combo.findText("Ahri"))
    ed._add()
    ed._combo.setCurrentIndex(ed._combo.findText("Orianna"))
    ed._add()
    assert changes[-1] == [103, 61]
    ed._list.setCurrentRow(1)
    ed._move(-1)
    assert changes[-1] == [61, 103]
    ed._list.setCurrentRow(0)
    ed._remove()
    assert changes[-1] == [103]


def test_tray_icon_builds(qtbot, tmp_path):
    from laa.ui.tray import make_icon

    assert not make_icon(paused=False).isNull()
    assert not make_icon(paused=True).isNull()
