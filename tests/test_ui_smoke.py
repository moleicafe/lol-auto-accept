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
    from laa import __version__
    assert win.windowTitle() == f"League Auto Accept v{__version__}"
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


def test_safety_lock_controls_write_config(qtbot, tmp_path):
    store = make_store(tmp_path)
    win = MainWindow(store, Bridge())
    qtbot.addWidget(win)
    win._safety.setChecked(True)
    assert store.get().safety_lock is True
    win._safety_buf.setValue(3)
    assert store.get().safety_lock_buffer_s == 3.0


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


def test_pause_syncs_between_window_and_tray(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    from laa.ui.tray import create_tray

    store = make_store(tmp_path)
    win = MainWindow(store, Bridge())
    qtbot.addWidget(win)
    tray = create_tray(QApplication.instance(), win, store)
    try:
        pause_action = tray.contextMenu().actions()[0]
        assert pause_action.text() == "Pause"

        # Tray -> window: toggling the tray action updates the window button
        # (and does not infinite-loop back through on_pause).
        pause_action.setChecked(True)
        assert win._pause.isChecked() is True
        assert store.get().master_paused is True

        pause_action.setChecked(False)
        assert win._pause.isChecked() is False
        assert store.get().master_paused is False

        # Window -> tray: toggling the window button updates the tray action.
        win._pause.setChecked(True)
        assert pause_action.isChecked() is True
        assert store.get().master_paused is True

        win._pause.setChecked(False)
        assert pause_action.isChecked() is False
        assert store.get().master_paused is False
    finally:
        tray.hide()


def test_app_tab_autostart_toggle(qtbot, tmp_path, monkeypatch):
    import laa.ui.autostart as autostart
    calls: list = []
    monkeypatch.setattr(autostart, "available", lambda: True)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "set_enabled", calls.append)
    win = MainWindow(make_store(tmp_path), Bridge())
    qtbot.addWidget(win)
    assert win._autostart.isEnabled()
    win._autostart.setChecked(True)
    assert calls == [True]


def test_autostart_checkbox_disabled_when_running_from_source(qtbot, tmp_path):
    win = MainWindow(make_store(tmp_path), Bridge())  # tests run unfrozen
    qtbot.addWidget(win)
    assert not win._autostart.isEnabled()


def test_update_available_shows_link_and_tray_message(qtbot, tmp_path):
    bridge = Bridge()
    win = MainWindow(make_store(tmp_path), bridge)
    qtbot.addWidget(win)
    assert not win._update_label.isVisible()
    bridge.update_available.emit("9.9.9", "https://example.com/rel")
    assert "9.9.9" in win._update_label.text()
    assert "https://example.com/rel" in win._update_label.text()


def test_check_updates_checkbox_writes_config(qtbot, tmp_path):
    store = make_store(tmp_path)
    win = MainWindow(store, Bridge())
    qtbot.addWidget(win)
    assert win._check_updates.isChecked()  # default on
    win._check_updates.setChecked(False)
    assert store.get().check_updates is False
