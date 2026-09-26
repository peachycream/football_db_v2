"""nflverse schedules -> core_schedule.

One file (release asset schedules/games.csv) holds every season from 1999, so
there is a single raw partition, 'all', and one load scope per season.

The schedule is a CURRENT-STATE feed: scores and kickoff times change while a
season is open, and next season's schedule appears in May. It is therefore
never marked final and is re-fetched on every run (it is ~2 MB)."""
import csv
import io

from .. import http, schedule
from ..loader import Loader, Scope

URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
POST_TYPES = {"WC", "DIV", "CON", "SB"}

# Real-world exceptions to the regular-season shape, each with a reason. A check
# that fails on reality gets a named exception here, never a looser tolerance.
# 2022 week 17 BUF @ CIN was declared no-contest after Damar Hamlin's cardiac
# arrest; it is absent from the schedule, so 2022 has 271 REG games.
CANCELLED_REG = {2022: {"BUF", "CIN"}}


class ScheduleLoader(Loader):
    id = "nflverse.schedules"
    source = "nflverse"
    endpoint = "schedules"
    table = "core_schedule"
    grain = "reference"
    ext = "csv"

    def partition(self, scope: Scope) -> str:
        return "all"

    def fetch(self, partition: str):
        return http.get(URL), {"url": URL}

    def parse(self, payload: bytes):
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        rows = list(reader)
        return list(reader.fieldnames or []), rows

    def reference_seasons(self, rows):
        return sorted({int(r["season"]) for r in rows})

    def scope_rows(self, rows, scope):
        return [r for r in rows if int(r["season"]) == scope.season]

    def scope_where(self, scope):
        return "season = ?", (scope.season,)

    def derive(self, row):
        gt = row["game_type"]
        if gt == "REG":
            return {"season_type": "REG"}
        if gt in POST_TYPES:
            return {"season_type": "POST"}
        raise ValueError(f"unknown game_type {gt!r} for {row['game_id']}")  # e.g. a preseason row appearing

    def raw_is_final(self, conn, partition):
        return False  # current-state feed; see module docstring

    def checks(self, conn, scope):
        s, fails = scope.season, []
        q = lambda sql, *p: conn.execute(sql, (s, *p)).fetchall()
        reg_games = q("SELECT COUNT(*) FROM core_schedule WHERE season=? AND season_type='REG'")[0][0]
        exp_games, exp_per_team = (272, 17) if s >= 2021 else (256, 16)
        cancelled = CANCELLED_REG.get(s, set())
        exp_games -= len(cancelled) // 2
        if reg_games != exp_games:
            fails.append(f"{s}: {reg_games} REG games, expected {exp_games}")
        per_team = q("""SELECT t, COUNT(*) n FROM (
                          SELECT home_team t FROM core_schedule WHERE season=? AND season_type='REG'
                          UNION ALL SELECT away_team FROM core_schedule WHERE season=? AND season_type='REG')
                        GROUP BY t""", s)
        if len(per_team) != 32:
            fails.append(f"{s}: {len(per_team)} teams in REG schedule, expected 32")
        bad = [f"{r['t']}={r['n']}" for r in per_team
               if r["n"] != exp_per_team - (1 if r["t"] in cancelled else 0)]
        if bad:
            fails.append(f"{s}: teams without {exp_per_team} REG games: {bad}")
        unmapped = q("""SELECT DISTINCT t FROM (
                          SELECT home_team t FROM core_schedule WHERE season=?
                          UNION SELECT away_team FROM core_schedule WHERE season=?) x
                        WHERE NOT EXISTS (SELECT 1 FROM team_aliases a
                                          WHERE a.abbr = x.t AND ? BETWEEN a.season_from AND a.season_to)""", s, s)
        if unmapped:
            fails.append(f"{s}: team values with no team_aliases row: {[r[0] for r in unmapped]}")
        twice = q("""SELECT week, t, COUNT(*) FROM (
                       SELECT week, home_team t FROM core_schedule WHERE season=? AND season_type='REG'
                       UNION ALL SELECT week, away_team FROM core_schedule WHERE season=? AND season_type='REG')
                     GROUP BY week, t HAVING COUNT(*) > 1""", s)
        if twice:
            fails.append(f"{s}: team scheduled twice in one week: {[tuple(r) for r in twice][:5]}")
        wrong = q("""SELECT game_id FROM core_schedule WHERE season=? AND result IS NOT NULL
                     AND result != home_score - away_score""")
        if wrong:
            fails.append(f"{s}: result != home_score - away_score on {len(wrong)} games")
        if schedule.season_is_closed(conn, s):
            post = q("SELECT COUNT(*) FROM core_schedule WHERE season=? AND season_type='POST'")[0][0]
            exp_post = 13 if s >= 2020 else 11
            if post != exp_post:
                fails.append(f"{s}: {post} POST games in a closed season, expected {exp_post}")
        return fails
