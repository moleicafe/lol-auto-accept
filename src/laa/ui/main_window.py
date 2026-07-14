from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
                               QPlainTextEdit, QPushButton, QSlider, QSystemTrayIcon,
                               QTabWidget, QVBoxLayout, QWidget)

import logging

from laa import __version__
from laa.ui import autostart
from laa.ui.assets import logo_icon
from laa.ui.bridge import Bridge
from laa.ui.store import ConfigStore

log = logging.getLogger(__name__)

SUMMONER_SPELLS = {
    1: "Cleanse", 3: "Exhaust", 4: "Flash", 6: "Ghost", 7: "Heal", 11: "Smite",
    12: "Teleport", 13: "Clarity", 14: "Ignite", 21: "Barrier", 32: "Mark",
}
MAX_LIST = 5


class ChampListEditor(QGroupBox):
    changed = Signal(list)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._ids: list[int] = []
        self._names: dict[int, str] = {}
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._list = QListWidget()
        add = QPushButton("Add")
        rm = QPushButton("Remove")
        up = QPushButton("Up")
        down = QPushButton("Down")
        add.clicked.connect(self._add)
        rm.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(+1))
        top = QHBoxLayout()
        top.addWidget(self._combo, 1)
        top.addWidget(add)
        side = QVBoxLayout()
        for b in (rm, up, down):
            side.addWidget(b)
        side.addStretch(1)
        mid = QHBoxLayout()
        mid.addWidget(self._list, 1)
        mid.addLayout(side)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(mid)

    def set_catalog(self, names: dict[int, str]) -> None:
        self._names = names
        self._combo.clear()
        for cid, name in sorted(names.items(), key=lambda kv: kv[1]):
            self._combo.addItem(name, cid)
        self._combo.setCurrentIndex(-1)
        completer = QCompleter([self._combo.itemText(i) for i in range(self._combo.count())])
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._combo.setCompleter(completer)
        self._refresh()

    def set_ids(self, ids: list[int]) -> None:
        self._ids = list(ids)[:MAX_LIST]
        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for cid in self._ids:
            self._list.addItem(self._names.get(cid, f"#{cid}"))

    def _add(self) -> None:
        idx = self._combo.currentIndex()
        if idx < 0:
            idx = self._combo.findText(self._combo.currentText(),
                                       Qt.MatchFlag.MatchFixedString)
        if idx < 0:
            return
        cid = self._combo.itemData(idx)
        if cid is None or cid in self._ids or len(self._ids) >= MAX_LIST:
            return
        self._ids.append(cid)
        self._refresh()
        self.changed.emit(list(self._ids))

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        del self._ids[row]
        self._refresh()
        self.changed.emit(list(self._ids))

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < len(self._ids):
            return
        self._ids[row], self._ids[new] = self._ids[new], self._ids[row]
        self._refresh()
        self._list.setCurrentRow(new)
        self.changed.emit(list(self._ids))


class MainWindow(QMainWindow):
    def __init__(self, store: ConfigStore, bridge: Bridge) -> None:
        super().__init__()
        self._store = store
        self.tray: QSystemTrayIcon | None = None
        self.setWindowTitle(f"League Auto Accept v{__version__}")
        self.setWindowIcon(logo_icon())
        self.resize(520, 640)
        cfg = store.get()

        self._status = QLabel("Waiting for League client")
        self._pause = QPushButton("Pause")
        self._pause.setCheckable(True)
        self._pause.setChecked(cfg.master_paused)
        self._pause.toggled.connect(lambda on: self._store.update(master_paused=on))

        tabs = QTabWidget()
        tabs.addTab(self._queue_tab(cfg), "Queue")
        tabs.addTab(self._champ_tab(cfg), "Champ Select")
        tabs.addTab(self._runes_tab(cfg), "Runes")
        tabs.addTab(self._app_tab(), "App")

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(100)
        self._log.setFixedHeight(120)

        central = QWidget()
        lay = QVBoxLayout(central)
        row = QHBoxLayout()
        row.addWidget(self._status, 1)
        row.addWidget(self._pause)
        lay.addLayout(row)
        lay.addWidget(tabs, 1)
        lay.addWidget(self._log)
        self.setCentralWidget(central)

        bridge.status.connect(self._status.setText)
        bridge.log_line.connect(self._log.appendPlainText)
        bridge.catalog_ready.connect(self._on_catalog)
        bridge.update_available.connect(self._on_update_available)

    def _queue_tab(self, cfg) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        auto = QCheckBox("Auto-accept ready check")
        auto.setChecked(cfg.auto_accept)
        auto.toggled.connect(lambda on: self._store.update(auto_accept=on))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 10)
        slider.setValue(int(cfg.accept_delay_s))
        self._delay_label = QLabel(f"{int(cfg.accept_delay_s)} s")
        slider.valueChanged.connect(self._on_delay)
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(self._delay_label)
        form.addRow(auto)
        form.addRow("Accept delay", row)
        return w

    def _on_delay(self, value: int) -> None:
        self._delay_label.setText(f"{value} s")
        self._store.update(accept_delay_s=float(value))

    def _on_safety_buffer(self, value: int) -> None:
        self._safety_buf_label.setText(f"{value} s")
        self._store.update(safety_lock_buffer_s=float(value))

    def _champ_tab(self, cfg) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._picks = ChampListEditor("Pick priority (top first)")
        self._picks.set_ids(cfg.pick_ids)
        self._picks.changed.connect(lambda ids: self._store.update(pick_ids=ids))
        self._bans = ChampListEditor("Ban priority (top first)")
        self._bans.set_ids(cfg.ban_ids)
        self._bans.changed.connect(lambda ids: self._store.update(ban_ids=ids))

        instalock = QCheckBox("Instalock (lock pick immediately)")
        instalock.setChecked(cfg.instalock)
        instalock.toggled.connect(lambda on: self._store.update(instalock=on))

        self._safety = QCheckBox("Auto-lock before timer runs out")
        self._safety.setChecked(cfg.safety_lock)
        self._safety.toggled.connect(lambda on: self._store.update(safety_lock=on))
        self._safety_buf = QSlider(Qt.Orientation.Horizontal)
        self._safety_buf.setRange(0, 5)
        self._safety_buf.setValue(int(cfg.safety_lock_buffer_s))
        self._safety_buf_label = QLabel(f"{int(cfg.safety_lock_buffer_s)} s")
        self._safety_buf.valueChanged.connect(self._on_safety_buffer)
        safety_row = QHBoxLayout()
        safety_row.addWidget(QLabel("Lock buffer"))
        safety_row.addWidget(self._safety_buf, 1)
        safety_row.addWidget(self._safety_buf_label)

        spells = QCheckBox("Set summoner spells")
        spells.setChecked(cfg.set_spells)
        spells.toggled.connect(lambda on: self._store.update(set_spells=on))
        spell1 = self._spell_combo(cfg.spell1_id, "spell1_id")
        spell2 = self._spell_combo(cfg.spell2_id, "spell2_id")
        flash_f = QCheckBox("Flash on F")
        flash_f.setChecked(cfg.flash_on_f)
        flash_f.toggled.connect(lambda on: self._store.update(flash_on_f=on))
        srow = QHBoxLayout()
        srow.addWidget(spells)
        srow.addWidget(spell1)
        srow.addWidget(spell2)
        srow.addWidget(flash_f)

        msg = QLineEdit(cfg.lobby_message)
        msg.setPlaceholderText("Lobby chat message (empty = off)")
        msg.editingFinished.connect(lambda: self._store.update(lobby_message=msg.text()))

        lay.addWidget(self._picks, 1)
        lay.addWidget(self._bans, 1)
        lay.addWidget(instalock)
        lay.addWidget(self._safety)
        lay.addLayout(safety_row)
        lay.addLayout(srow)
        lay.addWidget(msg)
        return w

    def _spell_combo(self, current: int, field_name: str) -> QComboBox:
        combo = QComboBox()
        for sid, name in sorted(SUMMONER_SPELLS.items(), key=lambda kv: kv[1]):
            combo.addItem(name, sid)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(
            lambda _i: self._store.update(**{field_name: combo.currentData()}))
        return combo

    def _runes_tab(self, cfg) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        runes = QCheckBox("Auto-import meta runes when my pick locks in")
        runes.setChecked(cfg.auto_runes)
        runes.toggled.connect(lambda on: self._store.update(auto_runes=on))
        meta_spells = QCheckBox("Also use meta summoner spells")
        meta_spells.setChecked(cfg.use_meta_spells)
        meta_spells.toggled.connect(lambda on: self._store.update(use_meta_spells=on))
        note = QLabel("Runes are written to a page named 'LAA: <Champion>'.\n"
                      "If the meta fetch fails, your current runes are left untouched.")
        note.setWordWrap(True)
        lay.addWidget(runes)
        lay.addWidget(meta_spells)
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    def _app_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._autostart = QCheckBox("Start with Windows (minimized to tray)")
        if autostart.available():
            self._autostart.setChecked(autostart.is_enabled())
            self._autostart.toggled.connect(self._on_autostart)
        else:
            self._autostart.setEnabled(False)
            self._autostart.setToolTip(
                "Available when running the packaged LeagueAutoAccept.exe")
        cfg = self._store.get()
        self._check_updates = QCheckBox("Check for updates on launch")
        self._check_updates.setChecked(cfg.check_updates)
        self._check_updates.toggled.connect(
            lambda on: self._store.update(check_updates=on))
        self._update_label = QLabel()
        self._update_label.setOpenExternalLinks(True)
        self._update_label.setVisible(False)
        version = QLabel(f"Version {__version__}")
        lay.addWidget(self._autostart)
        lay.addWidget(self._check_updates)
        lay.addWidget(self._update_label)
        lay.addWidget(version)
        lay.addStretch(1)
        return w

    def _on_update_available(self, version: str, url: str) -> None:
        self._update_label.setText(
            f'Update available: <a href="{url}">v{version} — download</a>')
        self._update_label.setVisible(True)
        log.info("Update available: v%s (%s)", version, url)
        if self.tray is not None:
            self.tray.showMessage(
                "Update available",
                f"League Auto Accept v{version} is out - open the App tab to download.")

    def _on_autostart(self, on: bool) -> None:
        try:
            autostart.set_enabled(on)
            log.info("Start with Windows %s", "enabled" if on else "disabled")
        except OSError as exc:
            log.warning("Could not update Start with Windows: %s", exc)

    def _on_catalog(self, names: dict) -> None:
        self._picks.set_catalog(names)
        self._bans.set_catalog(names)

    def closeEvent(self, event) -> None:
        if self.tray is not None and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            if not self._store.get().tray_hint_shown:
                self._store.update(tray_hint_shown=True)
                self.tray.showMessage("Still running",
                                      "League Auto Accept keeps working in the tray. "
                                      "Right-click the icon to quit.")
        else:
            super().closeEvent(event)
