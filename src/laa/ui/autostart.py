"""Start-with-Windows via the per-user Run registry key.

The registry is the single source of truth (no config field), so the checkbox
always reflects reality even if the user edits the registry or moves the exe.
Only meaningful for the packaged exe: from source there is no stable command
to register, so ``available()`` is False and the UI disables the option.
"""
from __future__ import annotations

import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "LeagueAutoAccept"


def available() -> bool:
    return bool(getattr(sys, "frozen", False))


def _command() -> str:
    return f'"{sys.executable}" --minimized'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
