# MLB Scoreboard

An 8-bit MLB scoreboard with live scores, linescores and standings from the MLB Stats API.

Today's slate loads when the app opens and refreshes itself every 30 seconds
while games are on (every five minutes otherwise). Open a game for its
inning-by-inning linescore, the bases, the count, who is batting and pitching,
probable pitchers before first pitch, and the winning and losing pitchers
after. Standings show each division's record, percentage and games back.

## Controls

* Up / Down: pick a game
* Left / Right: previous or next day on the scoreboard; previous or next game
  when a game is open; previous or next division in the standings
* Select: open the highlighted game; when a game is open, fetch it again now
* Menu: standings
* Back: return to the scoreboard, or back to today from another day

## Requirements

* Wi-Fi: scores come from https://statsapi.mlb.com, which needs no account or
  key. Put the network name and password in `secrets.py` (`WIFI_SSID` and
  `WIFI_PASSWORD`), for example through the Settings app.
* Times are shown in the badge's zone, taken from `TIMEZONE` in `secrets.py`
  (hours from UTC); without it they are shown in UTC.
* The last slate and standings are kept under `/state/mlb`, so the app can
  show its last scores without a connection.

`assets/teams.json` maps the 30 team ids to abbreviations, nicknames and
divisions; it was generated from the API's teams endpoint.
