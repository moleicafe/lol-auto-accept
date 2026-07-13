import sys

import pytest

import laa.ui.autostart as autostart


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values: dict[str, str] = {}

    def OpenKey(self, root, sub_key, reserved=0, access=0):
        return FakeKey()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, type_, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.fixture
def fake_reg(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(autostart, "winreg", fake)
    return fake


def test_disabled_by_default(fake_reg):
    assert autostart.is_enabled() is False


def test_enable_registers_exe_with_minimized_flag(fake_reg):
    autostart.set_enabled(True)
    assert autostart.is_enabled() is True
    command = fake_reg.values[autostart.VALUE_NAME]
    assert sys.executable in command
    assert "--minimized" in command


def test_disable_removes_entry(fake_reg):
    autostart.set_enabled(True)
    autostart.set_enabled(False)
    assert autostart.is_enabled() is False
    assert autostart.VALUE_NAME not in fake_reg.values


def test_disable_when_never_enabled_is_quiet(fake_reg):
    autostart.set_enabled(False)  # must not raise


def test_available_only_when_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert autostart.available() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart.available() is True
