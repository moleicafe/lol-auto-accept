# Manual integration checklist

Run against the real League client (a practice-tool or draft lobby). Check off each:

- [ ] App starts with client closed -> status "Waiting for League client"; no errors
- [ ] Start League client -> status flips to Connected; champion names appear in pickers
- [ ] Queue up -> ready check auto-accepted (try delay 0 and delay 3 s)
- [ ] Master pause on -> ready check NOT accepted
- [ ] Draft lobby: ban list top choice gets banned
- [ ] Pick list: top choice hovered; with instalock on, locked
- [ ] First pick banned by someone else -> falls through to second choice
- [ ] Summoner spells set; "Flash on F" places Flash on F
- [ ] Lobby message posted exactly once
- [ ] On lock-in: rune page "LAA: <Champion>" created and selected; re-lock next game
      overwrites the same page (no page-slot leak)
- [ ] Kill the League client mid-lobby -> app returns to "Waiting for League client",
      reconnects when client restarts
- [ ] Close button hides to tray (hint shown once); tray Quit exits; second app copy
      shows "already running" and exits
- [ ] `%APPDATA%\LeagueAutoAccept\laa.log` contains the session's actions
