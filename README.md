# League Auto Accept (Python)

A Python rebuild of [sweetriverfish/LeagueAutoAccept](https://github.com/sweetriverfish/LeagueAutoAccept)
with a GUI, system tray, and automatic meta rune import.

## Features
- Auto-accept the ready check (optional delay)
- Champ select: pick & ban from ordered fallback lists, optional instalock
- Summoner spell assignment with Flash-key (D/F) preference
- One-time lobby chat message
- **Auto meta runes:** when your pick locks in, the current meta rune page and
  (optionally) summoner spells for that champion/role are fetched from op.gg and
  written to a rune page named `LAA: <Champion>` — your other pages are never touched
- Everything individually toggleable; master pause in the system tray

## Run
Download `LeagueAutoAccept.exe` from releases and run it (the League client must be
running), or from source:

    python -m venv .venv
    .venv\Scripts\python -m pip install -e .
    .venv\Scripts\python -m laa

## Build the exe
    .venv\Scripts\python -m pip install -e ".[dev]"
    .\build.ps1

## Notes
- Windows only.
- Config and logs live in `%APPDATA%\LeagueAutoAccept\`.
- League Auto Accept isn't endorsed by Riot Games and doesn't reflect the views or
  opinions of Riot Games or anyone officially involved in producing or managing
  League of Legends. LCU automation of this kind is tolerated on most servers but
  violates Korean server policy — use at your own risk.
