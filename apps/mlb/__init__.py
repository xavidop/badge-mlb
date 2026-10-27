"""
An 8-bit MLB scoreboard: live scores, linescores and standings from the MLB Stats API.

Today's slate refreshes itself while games are on. Open a game for its
linescore, bases, count and pitchers, or flip to the division standings.

Controls:
* Up / Down = Pick a game
* Left / Right = Previous / next day, or previous / next game when open
* Select = Open the game, or fetch again now
* Menu = Standings (Left / Right change division)
* Back = Return to the scoreboard, or to today
"""

import json
import math
import os
import sys
import time

import fetch
import missing_details

try:
    import secrets
except ImportError:
    secrets = None

APP_DIR = "/system/apps/mlb"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

import mlbapi  # noqa: E402  (needs the app directory on the path)

badge.mode(HIRES | VSYNC)
screen.antialias = image.OFF

WIDTH, HEIGHT = screen.width, screen.height

CACHE_DIR = "/state/mlb"
TEMP_FILE = CACHE_DIR + "/download.tmp"
SCHEDULE_CACHE = CACHE_DIR + "/schedule.json"
STANDINGS_CACHE = CACHE_DIR + "/standings.json"
HEADERS = {"User-Agent": "GitHub Universe Badge 2026 MLB"}

LIVE_REFRESH_MS = 30000
IDLE_REFRESH_MS = 300000
GAME_REFRESH_MS = 20000
RETRY_MS = 15000
SPLASH_MS = 1500
REPEAT_FIRST_MS = 380
REPEAT_MS = 90

# ballpark palette: navy panel, red casing, cream type and amber bulbs
RED = color.rgb(200, 32, 40)
RED_DARK = color.rgb(130, 16, 24)
NAVY = color.rgb(16, 28, 56)
NAVY_DARK = color.rgb(8, 14, 30)
NAVY_LIGHT = color.rgb(32, 48, 88)
CREAM = color.rgb(240, 232, 208)
CREAM_DIM = color.rgb(150, 150, 140)
AMBER = color.rgb(255, 200, 48)
AMBER_DIM = color.rgb(96, 76, 24)
GREEN = color.rgb(72, 180, 96)
FIELD = color.rgb(40, 110, 60)
FIELD_DARK = color.rgb(22, 66, 36)
WHITE = color.rgb(255, 255, 255)

TITLE = font.futile          # 24px chunky heading
NUMBER = font.ignore         # 28px scores
BODY = font.nope             # 13px body text
SMALL = font.sins            # 12px labels and hints

# a 16x16 baseball drawn with rectangles
BALL = (
    ".....XXXXXX.....",
    "...XXWWWWWWXX...",
    "..XWWRWWWWRWWX..",
    ".XWWRWWWWWWRWWX.",
    ".XWRWWWWWWWWRWX.",
    "XWWRWWWWWWWWRWWX",
    "XWRWWWWWWWWWWRWX",
    "XWRWWWWWWWWWWRWX",
    "XWRWWWWWWWWWWRWX",
    "XWRWWWWWWWWWWRWX",
    "XWWRWWWWWWWWRWWX",
    ".XWRWWWWWWWWRWX.",
    ".XWWRWWWWWWRWWX.",
    "..XWWRWWWWRWWX..",
    "...XXWWWWWWXX...",
    ".....XXXXXX.....",
)
BALL_PENS = {"X": NAVY_DARK, "W": CREAM, "R": RED}

ROW_H = 22
ROWS = 8
LIST_TOP = 28

SPLASH, BOARD, GAME, STANDINGS = 0, 1, 2, 3

try:
    os.mkdir(CACHE_DIR)
except OSError:
    pass

TEAMS = mlbapi.Teams("assets/teams.json")


class Logos:
    """Team spot logos, loaded on first use.

    They ship at both 16 and 32 pixels (assets/logos16 and assets/logos) so
    the scoreboard's sixteen logos blit 1:1 instead of being scaled each frame,
    which cost 3ms a logo.
    """

    FOLDERS = {16: "assets/logos16", 32: "assets/logos"}

    def __init__(self):
        self.cache = {}

    def get(self, team_id, size):
        key = (team_id, size)
        if key in self.cache:
            return self.cache[key]
        picture = None
        path = "%s/%s.png" % (self.FOLDERS.get(size, "assets/logos"), team_id)
        if file_exists(path):
            try:
                picture = image.load(path)
            except (OSError, ValueError) as error:
                print("MLB: logo", team_id, "failed:", error)
        self.cache[key] = picture
        return picture

    def draw(self, team_id, x, y, size):
        picture = self.get(team_id, size)
        if picture is None:
            return False
        if picture.width == size:
            screen.blit(picture, vec2(x, y))
        else:
            screen.blit(picture, rect(0, 0, picture.width, picture.height), rect(x, y, size, size), image.BILINEAR)
        return True


LOGOS = Logos()


def utc_offset():
    """The badge's UTC offset in hours from secrets.py, else UTC."""
    try:
        return int(getattr(secrets, "TIMEZONE", 0) or 0)
    except (TypeError, ValueError):
        return 0


OFFSET = utc_offset()


def remove_file(path):
    try:
        os.remove(path)
    except OSError:
        pass


def clock_date():
    """Today from the badge clock, when something has set it."""
    try:
        now = time.localtime()
        if now[0] >= 2026:
            return "%04d-%02d-%02d" % (now[0], now[1], now[2])
    except (OSError, ValueError):
        pass
    return None


# ----------------------------------------------------------------------------
# one download, polled a frame at a time

class Fetch:
    """Stream a URL to a file; poll() answers True once, when the file is complete.

    The firmware's fetch advances every time it is tested for truth. `error`
    is set when it fails, and `headers` holds the reply headers when exposed.
    """

    def __init__(self, url, path):
        self.path = path
        self.error = None
        self.done = False
        self.headers = None
        self.missing = missing_details.missing("WIFI_SSID")
        if self.missing:
            self.error = "Add the Wi-Fi name and password in Settings"
            self.request = None
            return
        remove_file(path)
        self.request = fetch.url(url, headers=HEADERS).to(path)

    @property
    def status(self):
        if self.request is None:
            return "no wi-fi details"
        return self.request.state or "fetching"

    def poll(self):
        if self.done or self.error:
            return False
        finished = bool(self.request)
        if self.request.error:
            self.error = str(self.request.error)
            remove_file(self.path)
            return False
        if not finished:
            return False
        try:
            self.headers = self.request._fetch.http_response_headers
        except AttributeError:
            self.headers = None
        self.done = True
        return True


# ----------------------------------------------------------------------------
# the day's slate

today = None            # 'YYYY-MM-DD' once the API or the clock says


class Board:
    """The games of one day, refreshed on a timer while any are live."""

    def __init__(self, date=None):
        self.date = date            # None asks the API for its own today
        self.day = date
        self.games = []
        self.selected = 0
        self.fetch = None
        self.error = None
        self.status = "fetching scores"
        self.fetched_at = None
        self.next_at = 0
        self.cached = False
        if date is None and file_exists(SCHEDULE_CACHE):
            self.load(SCHEDULE_CACHE, cached=True)

    @property
    def is_today(self):
        return self.date is None or self.date == today

    @property
    def live(self):
        for game in self.games:
            if game["state"] == "Live":
                return True
        return False

    def load(self, path, cached=False):
        global today
        day, games = mlbapi.parse_schedule(path, TEAMS)
        if day is not None:
            self.day = day
            if self.date is None:
                today = day
        self.games = games
        self.selected = min(self.selected, max(0, len(games) - 1))
        self.cached = cached

    def refresh_now(self):
        self.next_at = 0
        self.error = None

    def update(self):
        global today
        if self.fetch is None:
            if badge.ticks < self.next_at:
                return
            self.fetch = Fetch(mlbapi.schedule_url(self.date), TEMP_FILE)
            self.status = "fetching scores"
            return
        self.status = self.fetch.status
        if self.fetch.poll():
            try:
                self.load(TEMP_FILE)
                if self.date is None:
                    if self.day is None:
                        today = mlbapi.header_date(self.fetch.headers) or clock_date() or today
                        self.day = today
                    os.rename(TEMP_FILE, SCHEDULE_CACHE)
                self.error = None
                self.fetched_at = badge.ticks
                self.next_at = badge.ticks + (LIVE_REFRESH_MS if self.live else IDLE_REFRESH_MS)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.fail("bad reply: %s" % error)
            remove_file(TEMP_FILE)
            self.fetch = None
        elif self.fetch.error:
            self.fail(self.fetch.error)
            self.fetch = None

    def fail(self, reason):
        print("MLB: schedule failed:", reason)
        self.error = reason
        self.next_at = badge.ticks + RETRY_MS

    def current(self):
        if not self.games:
            return None
        return self.games[self.selected]


# ----------------------------------------------------------------------------
# one game's linescore

class GameView:
    def __init__(self, game):
        self.game = game
        self.line = None
        self.fetch = None
        self.error = None
        self.status = "fetching linescore"
        self.next_at = 0
        self.path = "%s/game_%s.json" % (CACHE_DIR, game["pk"])
        if file_exists(self.path):
            try:
                self.line = mlbapi.parse_linescore(self.path)
            except (OSError, ValueError, TypeError):
                remove_file(self.path)

    def refresh_now(self):
        self.next_at = 0
        self.error = None

    def update(self):
        if self.game["state"] == "Preview" and self.line is not None:
            return
        if self.fetch is None:
            if badge.ticks < self.next_at:
                return
            self.fetch = Fetch(mlbapi.linescore_url(self.game["pk"]), TEMP_FILE)
            return
        self.status = self.fetch.status
        if self.fetch.poll():
            try:
                self.line = mlbapi.parse_linescore(TEMP_FILE)
                for name in os.listdir(CACHE_DIR):
                    if name.startswith("game_"):
                        remove_file(CACHE_DIR + "/" + name)
                os.rename(TEMP_FILE, self.path)
                self.error = None
                if self.game["state"] == "Live":
                    self.next_at = badge.ticks + GAME_REFRESH_MS
                else:
                    self.next_at = badge.ticks + IDLE_REFRESH_MS
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.error = "bad reply: %s" % error
                self.next_at = badge.ticks + RETRY_MS
            remove_file(TEMP_FILE)
            self.fetch = None
        elif self.fetch.error:
            self.error = self.fetch.error
            self.next_at = badge.ticks + RETRY_MS
            self.fetch = None


# ----------------------------------------------------------------------------
# standings

class Standings:
    def __init__(self):
        self.table = None
        self.division = 0
        self.fetch = None
        self.error = None
        self.status = "fetching standings"
        self.next_at = 0
        self.cached = False
        if file_exists(STANDINGS_CACHE):
            try:
                self.table = mlbapi.parse_standings(STANDINGS_CACHE, TEAMS)
                self.cached = True
            except (OSError, ValueError, TypeError):
                remove_file(STANDINGS_CACHE)

    def update(self):
        if self.fetch is None:
            if badge.ticks < self.next_at:
                return
            season = mlbapi.season_of(today) if today else 2026
            self.fetch = Fetch(mlbapi.standings_url(season), TEMP_FILE)
            return
        self.status = self.fetch.status
        if self.fetch.poll():
            try:
                self.table = mlbapi.parse_standings(TEMP_FILE, TEAMS)
                os.rename(TEMP_FILE, STANDINGS_CACHE)
                self.cached = False
                self.error = None
                self.next_at = badge.ticks + IDLE_REFRESH_MS * 6
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.error = "bad reply: %s" % error
                self.next_at = badge.ticks + RETRY_MS
            remove_file(TEMP_FILE)
            self.fetch = None
        elif self.fetch.error:
            self.error = self.fetch.error
            self.next_at = badge.ticks + RETRY_MS
            self.fetch = None


# ----------------------------------------------------------------------------
# drawing helpers

def write(text, x, y, pen, face=BODY):
    screen.font = face
    screen.pen = pen
    screen.text(text, x, y)


def text_width(text, face=BODY):
    screen.font = face
    return screen.measure_text(text)[0]


def write_centred(text, cx, y, pen, face=BODY):
    write(text, cx - text_width(text, face) // 2, y, pen, face)


def write_right(text, right, y, pen, face=BODY):
    write(text, right - text_width(text, face), y, pen, face)


def write_wrapped(text, x, y, w, h, pen, face=BODY):
    screen.font = face
    screen.pen = pen
    screen.text(text, rect(x, y, w, h), align=(LEFT, TOP))


def fill(x, y, w, h, pen):
    screen.pen = pen
    screen.rectangle(x, y, w, h)


def pixel_art(rows, pens, x, y, scale):
    for row, line in enumerate(rows):
        for column, key in enumerate(line):
            pen = pens.get(key)
            if pen is not None:
                fill(x + column * scale, y + row * scale, scale, scale, pen)


def draw_casing(title, right_text=None):
    """A ballpark look: a green outfield wall with red seam stitching down
    the sides, a dark scoreboard strip with amber lettering across the top,
    and the navy board in the middle."""
    fill(0, 0, WIDTH, HEIGHT, FIELD)
    fill(0, 0, WIDTH, 24, NAVY_DARK)
    fill(0, 24, WIDTH, 2, AMBER)
    for y in range(30, HEIGHT - 24, 8):
        fill(1, y, 2, 4, RED)
        fill(WIDTH - 3, y + 4, 2, 4, RED)
    pixel_art(BALL, BALL_PENS, 6, 4, 1)
    write(title, 28, 6, AMBER, BODY)
    if right_text:
        write_right(right_text, WIDTH - 8, 6, CREAM, BODY)
    fill(4, 26, WIDTH - 8, HEIGHT - 26 - 18, FIELD_DARK)
    fill(6, 28, WIDTH - 12, HEIGHT - 28 - 20, NAVY)


def draw_hints(hints):
    y = HEIGHT - 15
    x = 8
    for key, label in hints:
        fill(x, y, text_width(key, SMALL) + 4, 13, CREAM)
        write(key, x + 2, y, FIELD_DARK, SMALL)
        x += text_width(key, SMALL) + 7
        write(label, x, y, CREAM, SMALL)
        x += text_width(label, SMALL) + 10


def draw_bases(x, y, bases, size=7):
    """Three squares in a diamond; lit when a runner stands there."""
    spots = ((x + size + 2, y, bases[1]), (x, y + size + 2, bases[2]), (x + 2 * size + 4, y + size + 2, bases[0]))
    for bx, by, lit in spots:
        fill(bx - 1, by - 1, size + 2, size + 2, NAVY_DARK)
        fill(bx, by, size, size, AMBER if lit else NAVY_LIGHT)


def game_status(game, long=False):
    """What a game's row says about where it stands."""
    state = game["state"]
    detail = game["detail"]
    if state == "Final":
        if "Postponed" in detail or "Cancelled" in detail or "Suspended" in detail:
            return detail.upper()[:12]
        extra = ""
        if game["inning"] and game["inning"] != 9:
            extra = " F/%d" % game["inning"]
        return "FINAL" + extra
    if state == "Live":
        if detail not in ("In Progress", ""):
            return detail.upper()[:14]
        half = {"Top": "TOP", "Bottom": "BOT", "Middle": "MID", "End": "END"}.get(game["half"], game["half"].upper())
        inning = game["inning"] or "?"
        outs = game["outs"]
        if long:
            return "%s %s  %s OUT" % (half, inning, outs if outs is not None else "-")
        return "%s %s %s" % (half, inning, ("%d OUT" % outs) if outs is not None else "")
    if game["tbd"]:
        return "TBD"
    if detail and detail not in ("Scheduled", "Pre-Game", "Warmup"):
        return detail.upper()[:12]
    return mlbapi.local_time(game["start"], OFFSET)


def series_tag(game):
    series = game["series"]
    if not series or series == "Regular Season":
        return ""
    words = series.split()
    initials = "".join(word[0] for word in words if word)
    if game["series_game"]:
        return "%s G%s" % (initials, game["series_game"])
    return initials


def network_line(owner):
    """A status line for a screen: cached, fetching, or an error."""
    if owner.error:
        return ("NO WI-FI" if "Wi-Fi" in owner.error else "NO SIGNAL - " + owner.error[:30].upper()), RED
    if owner.fetch is not None:
        dots = "." * (1 + (badge.ticks // 300) % 3)
        return owner.status.upper() + dots, AMBER
    return None, None


# ----------------------------------------------------------------------------
# app state

mode = SPLASH
splash_at = None
board = Board()
game_view = None
standings = None
top = 0
light = 0.0


class Repeat:
    def __init__(self, button):
        self.button = button
        self.next_at = 0

    def fired(self):
        if badge.pressed(self.button):
            self.next_at = badge.ticks + REPEAT_FIRST_MS
            return True
        if badge.held(self.button) and badge.ticks >= self.next_at:
            self.next_at = badge.ticks + REPEAT_MS
            return True
        return False


up = Repeat(BUTTON_UP)
down = Repeat(BUTTON_DOWN)


def select_game(delta):
    global top
    if not board.games:
        return
    board.selected = min(len(board.games) - 1, max(0, board.selected + delta))
    if board.selected < top:
        top = board.selected
    elif board.selected >= top + ROWS:
        top = board.selected - ROWS + 1


def change_day(delta):
    """Another day's slate; back on today the cached board is reused."""
    global board, top
    base = board.day or today
    if base is None:
        return
    date = mlbapi.shift_date(base, delta)
    board = Board() if date == today else Board(date)
    top = 0


def back_to_today():
    global board, top
    board = Board()
    top = 0


def update_lights():
    global light
    fetching = (board.fetch is not None) or (game_view is not None and game_view.fetch is not None) \
        or (standings is not None and standings.fetch is not None)
    target = round(0.1 + 0.1 * math.sin(badge.ticks / 250), 2) if fetching else 0.0
    if target != light:
        light = target
        badge.caselights(light)


# ----------------------------------------------------------------------------
# screens

def draw_splash():
    fill(0, 0, WIDTH, HEIGHT, FIELD)
    fill(0, 0, WIDTH, 24, RED)
    bounce = int(abs(math.sin(badge.ticks / 300)) * 8)
    pixel_art(BALL, BALL_PENS, WIDTH // 2 - 48, 40 - bounce, 6)
    fill(0, 144, WIDTH, 60, NAVY)
    fill(0, 144, WIDTH, 2, NAVY_DARK)
    fill(0, 202, WIDTH, 2, NAVY_DARK)
    write_centred("MLB SCOREBOARD", WIDTH // 2, 152, CREAM, TITLE)
    write_centred("LIVE FROM THE MLB STATS API", WIDTH // 2, 182, AMBER, SMALL)
    if (badge.ticks // 400) % 2:
        write_centred("PRESS ANY BUTTON", WIDTH // 2, 216, CREAM, BODY)


def draw_board():
    day = board.day or today
    draw_casing("SCOREBOARD" if board.is_today else "SCOREBOARD  (BACK = TODAY)", mlbapi.pretty_date(day) if day else "DATE ?")
    if not board.games:
        if board.fetch is not None and not board.cached:
            write_centred("FETCHING TODAY'S GAMES", WIDTH // 2, 100, AMBER, BODY)
        elif board.error:
            write_centred("NO SIGNAL", WIDTH // 2, 86, RED, TITLE)
            write_wrapped(board.error, 40, 118, WIDTH - 80, 60, CREAM, SMALL)
        else:
            write_centred("NO GAMES THIS DAY", WIDTH // 2, 100, CREAM_DIM, BODY)
    for row in range(ROWS):
        index = top + row
        if index >= len(board.games):
            break
        game = board.games[index]
        y = LIST_TOP + row * ROW_H
        selected = index == board.selected
        if selected:
            fill(8, y - 1, WIDTH - 16, ROW_H - 2, CREAM)
        ink = NAVY_DARK if selected else CREAM
        dim = RED_DARK if selected else CREAM_DIM
        score_pen = RED_DARK if selected else AMBER
        tag = series_tag(game)
        if tag:
            write(tag, 12, y + 3, dim, SMALL)
        for side, x in (("away", 44), ("home", 142)):
            team = game[side]
            pen = ink if (game["state"] != "Final" or team["winner"]) else dim
            LOGOS.draw(team["id"], x, y + 2, 16)
            write(team["abbr"], x + 20, y + 2, pen, BODY)
            if team["score"] is not None:
                write_right(str(team["score"]), x + 80, y + 2, score_pen, BODY)
        write("@", 130, y + 3, dim, SMALL)
        status = game_status(game)
        live = game["state"] == "Live"
        write_right(status, WIDTH - 14, y + 3, (RED_DARK if selected else GREEN) if live else ink, SMALL)
    # the scroll marker when the slate is longer than the list
    if len(board.games) > ROWS:
        track_h = ROWS * ROW_H - 4
        knob = max(8, track_h * ROWS // len(board.games))
        knob_y = LIST_TOP + (track_h - knob) * top // max(1, len(board.games) - ROWS)
        fill(WIDTH - 9, LIST_TOP, 2, track_h, NAVY_DARK)
        fill(WIDTH - 9, knob_y, 2, knob, CREAM_DIM)
    line, pen = network_line(board)
    if line is None and board.cached:
        line, pen = "SHOWING SAVED SCORES", CREAM_DIM
    elif line is None and board.fetched_at is not None:
        age = (badge.ticks - board.fetched_at) // 1000
        line, pen = ("UPDATED %ds AGO" % age if age < 120 else "UPDATED %dm AGO" % (age // 60)), CREAM_DIM
    if line:
        write(line[:44], 12, HEIGHT - 32, pen, SMALL)
    draw_hints((("^v", "GAME"), ("<>", "DAY"), ("SEL", "OPEN"), ("MENU", "STANDINGS")))


def draw_game():
    game = game_view.game
    line = game_view.line
    tag = game["series"].upper() if game["series"] and game["series"] != "Regular Season" else "REGULAR SEASON"
    if game["series_game"] and tag != "REGULAR SEASON":
        tag += " GAME %s" % game["series_game"]
    draw_casing(tag[:26], mlbapi.pretty_date(board.day or today or ""))

    # the scoreline: away on the left, home on the right
    for side, x, align in (("away", 12, "left"), ("home", WIDTH - 12, "right")):
        team = game[side]
        score = team["score"] if team["score"] is not None else "-"
        if align == "left":
            LOGOS.draw(team["id"], x, 30, 32)
            write(team["abbr"], x + 38, 30, CREAM, TITLE)
            write(team["name"].upper()[:10], x + 38, 54, CREAM_DIM, SMALL)
            write(str(score), x + 100, 28, AMBER, NUMBER)
        else:
            LOGOS.draw(team["id"], x - 32, 30, 32)
            write_right(team["abbr"], x - 38, 30, CREAM, TITLE)
            write_right(team["name"].upper()[:10], x - 38, 54, CREAM_DIM, SMALL)
            write_right(str(score), x - 100, 28, AMBER, NUMBER)
    status = game_status(game, long=True)
    write_centred(status, WIDTH // 2, 34, GREEN if game["state"] == "Live" else CREAM, SMALL)
    write_centred("@", WIDTH // 2, 54, CREAM_DIM, SMALL)

    # the linescore grid: the last nine innings played, then R H E
    grid_y = 74
    innings = line["innings"] if line else []
    scheduled = line["scheduled"] if line else 9
    count = max(scheduled, len(innings))
    first = max(1, count - 8)
    cell = 20
    x0 = 50
    fill(10, grid_y, WIDTH - 20, 3 * 16 + 4, NAVY_DARK)
    for column in range(9):
        number = first + column
        if number > count:
            break
        write_centred(str(number), x0 + column * cell + cell // 2, grid_y + 2, CREAM_DIM, SMALL)
    for column, label in enumerate(("R", "H", "E")):
        write_centred(label, x0 + 9 * cell + 6 + column * 22 + 11, grid_y + 2, AMBER, SMALL)
    for row, side in enumerate(("away", "home")):
        y = grid_y + 18 + row * 16
        write(game[side]["abbr"], 14, y, CREAM, SMALL)
        for column in range(9):
            number = first + column
            runs = None
            for num, away_runs, home_runs in innings:
                if num == number:
                    runs = away_runs if side == "away" else home_runs
            if runs is not None:
                write_centred(str(runs), x0 + column * cell + cell // 2, y, CREAM, SMALL)
            elif number <= count:
                write_centred("-", x0 + column * cell + cell // 2, y, NAVY_LIGHT, SMALL)
        totals = line[side] if line else (game[side]["score"], None, None)
        for column, value in enumerate(totals):
            write_centred(str(value) if value is not None else "-", x0 + 9 * cell + 6 + column * 22 + 11, y, AMBER, SMALL)

    # bases, count and who is up, or pitchers around the game
    info_y = 132
    if game["state"] == "Live":
        bases = line["bases"] if line else game["bases"]
        draw_bases(20, info_y + 4, bases)
        balls = line["balls"] if line else game["balls"]
        strikes = line["strikes"] if line else game["strikes"]
        outs = line["outs"] if line else game["outs"]
        write("B %s  S %s  O %s" % (balls if balls is not None else "-", strikes if strikes is not None else "-", outs if outs is not None else "-"), 60, info_y + 8, CREAM, BODY)
        if line and line["batter"]:
            write("AT BAT", 150, info_y, CREAM_DIM, SMALL)
            write(line["batter"][:16], 150, info_y + 12, CREAM, BODY)
        if line and line["pitcher"]:
            write("PITCHING", 150, info_y + 30, CREAM_DIM, SMALL)
            write(line["pitcher"][:16], 150, info_y + 42, CREAM, BODY)
    elif game["state"] == "Final":
        facts = (("W", game["winner_pitcher"]), ("L", game["loser_pitcher"]), ("SV", game["save_pitcher"]))
        x = 14
        for label, name in facts:
            if not name:
                continue
            write(label, x, info_y + 2, AMBER, SMALL)
            write(name[:14], x + text_width(label, SMALL) + 6, info_y + 1, CREAM, BODY)
            x += text_width(label, SMALL) + text_width(name[:14], BODY) + 22
    else:
        write("PROBABLE PITCHERS", 14, info_y, CREAM_DIM, SMALL)
        write("%s: %s" % (game["away"]["abbr"], game["away"]["probable"] or "TBD"), 14, info_y + 13, CREAM, BODY)
        write("%s: %s" % (game["home"]["abbr"], game["home"]["probable"] or "TBD"), 14, info_y + 29, CREAM, BODY)
        write("FIRST PITCH %s" % mlbapi.local_time(game["start"], OFFSET), 180, info_y + 13, AMBER, BODY)
    if game["venue"]:
        write(game["venue"].upper()[:40], 14, 186, CREAM_DIM, SMALL)
    line_text, pen = network_line(game_view)
    if line_text:
        write(line_text[:44], 14, 200, pen, SMALL)
    elif game_view.line is None:
        write("NO LINESCORE YET", 14, 200, CREAM_DIM, SMALL)
    draw_hints((("<>", "PREV/NEXT"), ("SEL", "REFRESH"), ("BACK", "SCORES")))


def draw_standings():
    division_id, division_name = mlbapi.DIVISIONS[standings.division]
    draw_casing("STANDINGS", "%d/%d" % (standings.division + 1, len(mlbapi.DIVISIONS)))
    write(division_name, 14, 30, AMBER, TITLE)
    rows = (standings.table or {}).get(division_id) or []
    columns = (("W", 170), ("L", 206), ("PCT", 252), ("GB", 294))
    for label, x in columns:
        write_right(label, x, 60, CREAM_DIM, SMALL)
    fill(10, 73, WIDTH - 20, 1, NAVY_LIGHT)
    if not rows:
        line, pen = network_line(standings)
        write_centred(line or "NO STANDINGS", WIDTH // 2, 120, pen or CREAM_DIM, BODY)
    for index, row in enumerate(rows[:5]):
        y = 78 + index * 22
        if index == 0:
            fill(10, y - 2, WIDTH - 20, 20, NAVY_LIGHT)
        write(str(index + 1), 14, y + 1, CREAM_DIM, SMALL)
        LOGOS.draw(row["id"], 26, y, 16)
        write(row["abbr"] + ("*" if row["clinched"] else ""), 46, y, CREAM, BODY)
        write(row["name"].upper()[:9], 94, y + 1, CREAM_DIM, SMALL)
        write_right(str(row["wins"]), 170, y, CREAM, BODY)
        write_right(str(row["losses"]), 206, y, CREAM, BODY)
        write_right(row["pct"], 252, y, AMBER, BODY)
        write_right(row["gb"], 294, y, CREAM, BODY)
    line, pen = network_line(standings)
    if line is None and standings.cached:
        line, pen = "SHOWING SAVED STANDINGS", CREAM_DIM
    if line:
        write(line[:44], 14, 196, pen, SMALL)
    elif rows:
        write("* CLINCHED", 14, 196, CREAM_DIM, SMALL)
    draw_hints((("<>", "DIVISION"), ("BACK", "SCORES")))


# ----------------------------------------------------------------------------
# input per screen

def update_splash():
    global mode, splash_at
    if splash_at is None:
        splash_at = badge.ticks
    board.update()
    if badge.ticks - splash_at > SPLASH_MS and badge.pressed():
        mode = BOARD
    elif badge.ticks - splash_at > SPLASH_MS * 4:
        mode = BOARD
    draw_splash()


def update_board():
    global mode, game_view, standings
    if up.fired():
        select_game(-1)
    if down.fired():
        select_game(1)
    if badge.pressed(BUTTON_LEFT):
        change_day(-1)
    if badge.pressed(BUTTON_RIGHT):
        change_day(1)
    if badge.pressed(BUTTON_BACK) and not board.is_today:
        back_to_today()
    if badge.pressed(BUTTON_MENU):
        if standings is None:
            standings = Standings()
        mode = STANDINGS
    if badge.pressed(BUTTON_SELECT):
        game = board.current()
        if game is not None:
            game_view = GameView(game)
            mode = GAME
            return
        board.refresh_now()
    board.update()
    draw_board()


def update_game():
    global mode, game_view
    if badge.pressed(BUTTON_BACK):
        game_view = None
        mode = BOARD
        return
    if badge.pressed(BUTTON_LEFT) and board.selected > 0:
        select_game(-1)
        game_view = GameView(board.current())
    elif badge.pressed(BUTTON_RIGHT) and board.selected < len(board.games) - 1:
        select_game(1)
        game_view = GameView(board.current())
    if badge.pressed(BUTTON_SELECT):
        game_view.refresh_now()
        board.refresh_now()
    board.update()
    # the slate may have refreshed under us; keep the row's data current
    current = board.current()
    if current is not None and current["pk"] == game_view.game["pk"]:
        game_view.game = current
    game_view.update()
    draw_game()


def update_standings():
    global mode
    if badge.pressed(BUTTON_BACK) or badge.pressed(BUTTON_MENU):
        mode = BOARD
        return
    if badge.pressed(BUTTON_LEFT):
        standings.division = (standings.division - 1) % len(mlbapi.DIVISIONS)
    if badge.pressed(BUTTON_RIGHT):
        standings.division = (standings.division + 1) % len(mlbapi.DIVISIONS)
    board.update()
    standings.update()
    draw_standings()


def update():
    if mode == SPLASH:
        update_splash()
    elif mode == BOARD:
        update_board()
    elif mode == GAME:
        update_game()
    else:
        update_standings()
    update_lights()


def on_exit():
    badge.caselights(0)


remove_file(TEMP_FILE)
run(update)
