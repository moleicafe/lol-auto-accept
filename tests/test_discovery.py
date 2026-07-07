from laa.lcu.discovery import LCUCredentials, parse_cmdline

CMDLINE = (
    '"C:/Riot Games/League of Legends/LeagueClientUx.exe" '
    '--riotclient-auth-token=xyz --app-port=52345 '
    '--remoting-auth-token=AbC-123_dEf --app-pid=1234'
)


def test_parse_cmdline_extracts_port_and_token():
    creds = parse_cmdline(CMDLINE)
    assert creds == LCUCredentials(port=52345, token="AbC-123_dEf")


def test_parse_cmdline_missing_flags_returns_none():
    assert parse_cmdline("LeagueClientUx.exe --app-port=1") is None
    assert parse_cmdline("") is None
