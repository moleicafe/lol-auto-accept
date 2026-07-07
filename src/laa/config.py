from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FLASH_ID = 4


@dataclass
class Config:
    schema_version: int = SCHEMA_VERSION
    master_paused: bool = False
    # queue
    auto_accept: bool = True
    accept_delay_s: float = 0.0
    # champ select
    pick_ids: list[int] = field(default_factory=list)
    ban_ids: list[int] = field(default_factory=list)
    instalock: bool = False
    set_spells: bool = False
    spell1_id: int = 4
    spell2_id: int = 14
    flash_on_f: bool = True
    lobby_message: str = ""
    # runes
    auto_runes: bool = True
    use_meta_spells: bool = False
    # ui
    tray_hint_shown: bool = False


def config_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "LeagueAutoAccept"


def config_path() -> Path:
    return config_dir() / "config.json"


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            log.warning("Corrupt config at %s (not a JSON object); using defaults", path)
            return Config()
        known = {f.name for f in dataclasses.fields(Config)}
        return Config(**{k: v for k, v in raw.items() if k in known})
    except FileNotFoundError:
        return Config()
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Corrupt config at %s (%s); using defaults", path, exc)
        return Config()


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(cfg), indent=2), encoding="utf-8")
    tmp.replace(path)
