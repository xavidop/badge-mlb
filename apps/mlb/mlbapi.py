"""MLB Stats API records distilled for the badge.

The API (statsapi.mlb.com, no key needed) accepts a `fields` list that prunes
its replies, so a whole day's slate with linescores is about 12KB and a game's
linescore about 2KB. Everything here is plain parsing of those replies into
small dicts the screens can draw, plus date and time helpers, since the badge
has no timezone database: it knows only its offset from UTC in hours.
"""

import json

API = "https://statsapi.mlb.com/api/v1/"

SCHEDULE_FIELDS = (
    "dates,date,games,gamePk,gameDate,status,abstractGameState,detailedState,"
    "startTimeTBD,teams,away,home,score,isWinner,team,id,name,probablePitcher,"
    "fullName,decisions,winner,loser,save,linescore,currentInning,inningState,"
    "outs,balls,strikes,offense,first,second,third,seriesDescription,"
    "seriesGameNumber,gamesInSeries,description,venue"
)
LINESCORE_FIELDS = (
    "currentInning,inningState,scheduledInnings,innings,num,home,away,runs,hits,"
    "errors,teams,balls,strikes,outs,offense,batter,fullName,first,second,third,"
    "defense,pitcher"
)
STANDINGS_FIELDS = (
    "records,division,id,teamRecords,team,id,wins,losses,winningPercentage,"
    "gamesBack,wildCardGamesBack,divisionRank,streak,streakCode,clinched"
)

DIVISIONS = (
    (201, "AL EAST"), (202, "AL CENTRAL"), (200, "AL WEST"),
    (204, "NL EAST"), (205, "NL CENTRAL"), (203, "NL WEST"),
)

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

ACCENTS = {
    "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n",
    "ü": "u", "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
    "Ñ": "N", "è": "e", "à": "a", "ç": "c",
}


def schedule_url(date=None):
    url = API + "schedule?sportId=1&hydrate=linescore,probablePitcher,decisions&fields=" + SCHEDULE_FIELDS
    if date:
        url += "&date=" + date
    return url


def linescore_url(game_pk):
    return "%sgame/%d/linescore?fields=%s" % (API, game_pk, LINESCORE_FIELDS)


def standings_url(season):
    return "%sstandings?leagueId=103,104&season=%d&standingsTypes=regularSeason&fields=%s" % (API, season, STANDINGS_FIELDS)


def ascii(text):
    """Player and venue names without accents, which the badge fonts lack."""
    if not text:
        return ""
    out = []
    for char in text:
        if char in ACCENTS:
            out.append(ACCENTS[char])
        elif 32 <= ord(char) < 127:
            out.append(char)
    return "".join(out)


def short_name(full_name):
    """'Brandon Woodruff' as 'B. Woodruff'."""
    parts = ascii(full_name).split()
    if len(parts) < 2:
        return parts[0] if parts else ""
    return parts[0][0] + ". " + " ".join(parts[1:])


class Teams:
    """The bundled team table: id -> (abbreviation, nickname, division id)."""

    def __init__(self, path):
        self.table = {}
        try:
            with open(path) as handle:
                for key, value in json.load(handle).items():
                    self.table[int(key)] = tuple(value)
        except (OSError, ValueError) as error:
            print("MLB: no team table:", error)

    def abbreviation(self, team_id, fallback="???"):
        entry = self.table.get(team_id)
        return entry[0] if entry else fallback

    def nickname(self, team_id, fallback=""):
        entry = self.table.get(team_id)
        return entry[1] if entry else fallback


# ----------------------------------------------------------------------------
# dates and times

def is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year, month):
    if month == 2:
        return 29 if is_leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def split_date(date):
    year, month, day = date.split("-")
    return int(year), int(month), int(day)


def shift_date(date, delta):
    """'2026-10-27' moved by delta days, either way."""
    year, month, day = split_date(date)
    while delta > 0:
        day += 1
        if day > days_in_month(year, month):
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
        delta -= 1
    while delta < 0:
        day -= 1
        if day < 1:
            month -= 1
            if month < 1:
                month = 12
                year -= 1
            day = days_in_month(year, month)
        delta += 1
    return "%04d-%02d-%02d" % (year, month, day)


def weekday(date):
    """Zeller's congruence, Monday as 0."""
    year, month, day = split_date(date)
    if month < 3:
        month += 12
        year -= 1
    century, year = divmod(year, 100)
    h = (day + 13 * (month + 1) // 5 + year + year // 4 + century // 4 + 5 * century) % 7
    return (h + 5) % 7


def pretty_date(date):
    try:
        year, month, day = split_date(date)
        return "%s %s %d" % (WEEKDAYS[weekday(date)], MONTHS[month - 1], day)
    except (ValueError, IndexError):
        return date


def season_of(date):
    """Standings for the year of this date; January and February look back."""
    year, month, _ = split_date(date)
    return year - 1 if month < 3 else year


def local_time(iso, offset_hours):
    """'2026-10-28T00:00:00Z' as '5:00PM' in a zone offset_hours from UTC."""
    try:
        clock = iso.split("T")[1].rstrip("Z")
        hour, minute = int(clock[0:2]), int(clock[3:5])
    except (IndexError, ValueError):
        return "TBD"
    hour = (hour + int(offset_hours)) % 24
    suffix = "AM" if hour < 12 else "PM"
    hour = hour % 12 or 12
    return "%d:%02d%s" % (hour, minute, suffix)


def header_date(headers):
    """'2026-10-27' from an HTTP Date header, or None."""
    try:
        value = headers.get("Date") or headers.get("date")
        _, day, month, year = value.split(" ")[:4]
        return "%04d-%02d-%02d" % (int(year), MONTHS.index(month.upper()) + 1, int(day))
    except (AttributeError, ValueError, IndexError):
        return None


# ----------------------------------------------------------------------------
# replies

def _side(entry, teams):
    team = entry.get("team") or {}
    team_id = team.get("id")
    pitcher = entry.get("probablePitcher") or {}
    return {
        "id": team_id,
        "abbr": teams.abbreviation(team_id, (team.get("name") or "???")[:3].upper()),
        "name": teams.nickname(team_id, ascii(team.get("name"))),
        "score": entry.get("score"),
        "winner": bool(entry.get("isWinner")),
        "probable": short_name(pitcher.get("fullName")),
    }


def parse_schedule(path, teams):
    """(date, games) from a schedule reply; date is None when it listed no day."""
    with open(path) as handle:
        reply = json.load(handle)
    dates = reply.get("dates") or []
    if not dates:
        return None, []
    day = dates[0]
    games = []
    for raw in day.get("games") or []:
        status = raw.get("status") or {}
        line = raw.get("linescore") or {}
        offense = line.get("offense") or {}
        decisions = raw.get("decisions") or {}
        series = raw.get("seriesDescription") or ""
        games.append({
            "pk": raw.get("gamePk"),
            "away": _side((raw.get("teams") or {}).get("away") or {}, teams),
            "home": _side((raw.get("teams") or {}).get("home") or {}, teams),
            "state": status.get("abstractGameState") or "Preview",
            "detail": status.get("detailedState") or "",
            "tbd": bool(status.get("startTimeTBD")),
            "start": raw.get("gameDate") or "",
            "inning": line.get("currentInning"),
            "half": line.get("inningState") or "",
            "outs": line.get("outs"),
            "balls": line.get("balls"),
            "strikes": line.get("strikes"),
            "bases": (bool(offense.get("first")), bool(offense.get("second")), bool(offense.get("third"))),
            "series": series,
            "series_game": raw.get("seriesGameNumber"),
            "series_games": raw.get("gamesInSeries"),
            "description": raw.get("description") or "",
            "venue": ascii((raw.get("venue") or {}).get("name")),
            "winner_pitcher": short_name((decisions.get("winner") or {}).get("fullName")),
            "loser_pitcher": short_name((decisions.get("loser") or {}).get("fullName")),
            "save_pitcher": short_name((decisions.get("save") or {}).get("fullName")),
        })
    return day.get("date"), games


def parse_linescore(path):
    with open(path) as handle:
        reply = json.load(handle)
    innings = []
    for raw in reply.get("innings") or []:
        innings.append((raw.get("num"), (raw.get("away") or {}).get("runs"), (raw.get("home") or {}).get("runs")))
    totals = reply.get("teams") or {}
    offense = reply.get("offense") or {}
    defense = reply.get("defense") or {}

    def line(side):
        entry = totals.get(side) or {}
        return (entry.get("runs"), entry.get("hits"), entry.get("errors"))

    return {
        "innings": innings,
        "scheduled": reply.get("scheduledInnings") or 9,
        "away": line("away"),
        "home": line("home"),
        "inning": reply.get("currentInning"),
        "half": reply.get("inningState") or "",
        "balls": reply.get("balls"),
        "strikes": reply.get("strikes"),
        "outs": reply.get("outs"),
        "bases": (bool(offense.get("first")), bool(offense.get("second")), bool(offense.get("third"))),
        "batter": short_name((offense.get("batter") or {}).get("fullName")),
        "pitcher": short_name((defense.get("pitcher") or {}).get("fullName")),
    }


def parse_standings(path, teams):
    """{division id: [rows]} with rows as dicts, in the API's rank order."""
    with open(path) as handle:
        reply = json.load(handle)
    table = {}
    for record in reply.get("records") or []:
        division = (record.get("division") or {}).get("id")
        rows = []
        for raw in record.get("teamRecords") or []:
            team_id = (raw.get("team") or {}).get("id")
            rows.append({
                "id": team_id,
                "abbr": teams.abbreviation(team_id),
                "name": teams.nickname(team_id),
                "wins": raw.get("wins") or 0,
                "losses": raw.get("losses") or 0,
                "pct": raw.get("winningPercentage") or "-",
                "gb": raw.get("gamesBack") or "-",
                "wcgb": raw.get("wildCardGamesBack") or "-",
                "streak": (raw.get("streak") or {}).get("streakCode") or "",
                "clinched": bool(raw.get("clinched")),
            })
        if division is not None:
            table[division] = rows
    if not table:
        raise ValueError("no standings in reply")
    return table
