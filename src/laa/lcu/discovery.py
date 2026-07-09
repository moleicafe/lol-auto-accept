from __future__ import annotations

import re
from dataclasses import dataclass

import psutil

PROCESS_NAME = "LeagueClientUx.exe"
_PORT_RE = re.compile(r"--app-port=(\d+)")
_TOKEN_RE = re.compile(r"--remoting-auth-token=([\w-]+)")


@dataclass(frozen=True)
class LCUCredentials:
    port: int
    token: str


def parse_cmdline(cmdline: str) -> LCUCredentials | None:
    port_m = _PORT_RE.search(cmdline)
    token_m = _TOKEN_RE.search(cmdline)
    if not port_m or not token_m:
        return None
    return LCUCredentials(port=int(port_m.group(1)), token=token_m.group(1))


def find_credentials() -> LCUCredentials | None:
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] == PROCESS_NAME and proc.info["cmdline"]:
                creds = parse_cmdline(" ".join(proc.info["cmdline"]))
                if creds:
                    return creds
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None
