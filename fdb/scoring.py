"""Fantasy scoring at READ time (REBUILD_DESIGN §6; hard rule 4: nothing stored).

MFL rules come verbatim from core_mfl_rules (via mart_mfl_rules):
  positions  'QB|RB|WR|TE|DT|DE|LB|CB|S' (the catch-all row) or narrower
  event      'PY', 'TK', '#P', ...
  range      '-50-999'  the rule applies when the player's value lies in it
  points     '*0.05'    per unit
             '5/300'    5 points per FULL 300 units (truncated; never negative)
             '6'        flat, once, when the value is in range

RESOLUTION - measured against MFL's OWN reported points, not reasoned from the rule
text: a rule applies only to the positions it NAMES, and for a player at position P
EVERY rule naming P applies - the catch-all row and any narrower row are ADDITIVE.
30590 2025 wk1-3, players whose predicted points equal MFL's reported to 0.01:
    resolution          TE        WR        RB        QB
    widest group only   7/217    11/446    44/288    98/117
    ADDITIVE          175/217   286/446   170/288    98/117
    narrowest only      7/217    10/446     4/288    98/117
This refines, and does not contradict, the settled catch-all rule (v1 diag_proj_14):
a narrow row is not an OVERRIDE of the catch-all - it adds to it. (IDP exactness is
low whatever the resolution: MFL scores its own tackle stats, not PFF's, which is
why the empirical IDP calibration exists.) An event with only narrow rows (RA: RB,
WR, TE each *0.75) scores only for those positions - applying it to a QB gave
Darnold 25.4 instead of MFL's 20.9 on the first run; resolved, it is exact.
The catch-all rows name QB/RB/WR/TE too, so an offensive player's SPECIAL-TEAMS
tackles score (TK *5, AS *1.5 in 30590): the mart carries nflverse's
def_tackles_solo / def_tackle_assists on offense rows for exactly that. Verified: 30590's rules reproduce MFL's
reported 20.9 for Darnold 2025 wk1 exactly this way (REBUILD_LOG Phase 3).

v1 could not do this: its rules table was UNIQUE on (league, positions, event,
range), so the four PY rows collapsed into ONE ('10/500' -> 0.02/yd) - the cause of
v1's 7.60-vs-20.9 Darnold discrepancy. Scoring is therefore per PLAYER-GAME here
(bonuses are per game), which is why the matchup mart keeps player-game rows.
"""
import math
import re
from collections import defaultdict

# mart column -> MFL event codes in preference order (v1 matchups.py STAT_EVENTS,
# offense/IDP; the event vocabulary was enumerated from the six leagues' rules).
STAT_EVENTS = {
    "pass_yards": ["PY"], "pass_tds": ["#P"], "completions": ["PC"], "interceptions": ["IN"],
    "sacks": ["TSK"], "carries": ["RA"], "rush_yards": ["RY"], "rush_tds": ["#R"],
    "targets": ["TGT"], "receptions": ["CC"], "rec_yards": ["CY"], "rec_tds": ["#C"],
    "passing_2pt": ["P2"], "rushing_2pt": ["R2"], "receiving_2pt": ["C2"],
    "fumbles_lost": ["FLO", "FL"], "kr_yards": ["KY"], "pr_yards": ["UY"],
    "def_tackles": ["TK"], "def_assists": ["AS"], "def_tfl": ["TKL"], "def_sacks": ["SK"],
    "def_qb_hits": ["QH"], "def_pass_breakups": ["PD"], "def_batted_passes": ["PD"],
    "def_interceptions": ["IC"], "def_int_tds": ["#IR"], "def_forced_fumbles": ["FF"],
    "def_fumble_recoveries": ["FC", "FR"], "def_fr_tds": ["#DR"], "def_safeties": ["SF"], "def_tds": ["#DR"],
}
# Never scored (reported to the caller): v1 UNSCORABLE, with v2's corrections.
UNSCORABLE = {
    "fumbles": "rushing fumbles only (nflverse rushing_fumbles); fumbles_lost is the scored column",
    "fumbles_total": "total fumbles - descriptive; leagues score fumbles LOST",
    "sack_yards": "no MFL event code for sack yardage in any registered league",
    "special_teams_tds": "cannot be split into the #KT / #UT return-TD codes",
    "passing_first_downs": "no registered MFL league scores first downs",
    "rushing_first_downs": "no registered MFL league scores first downs",
    "receiving_first_downs": "no registered MFL league scores first downs",
    "def_stops": "descriptive only (PFF charting, no fantasy event)",
    "def_pressures": "descriptive only (PFF charting, no fantasy event)",
    "def_snaps": "descriptive only", "def_cov_targets": "descriptive only (coverage volume faced)",
    "def_cov_receptions": "descriptive only (coverage volume allowed)",
    "def_cov_yards": "descriptive only (coverage yardage allowed)",
}
# Generic default (v1 PPR_POINTS verbatim): offense standard full PPR; the IDP half a
# documented house baseline, not a standard.
PPR_POINTS = {
    "pass_yards": 0.04, "pass_tds": 4.0, "interceptions": -2.0, "rush_yards": 0.1, "rush_tds": 6.0,
    "receptions": 1.0, "rec_yards": 0.1, "rec_tds": 6.0, "passing_2pt": 2.0, "rushing_2pt": 2.0,
    "receiving_2pt": 2.0, "def_tackles": 1.5, "def_assists": 0.75, "def_tfl": 1.0, "def_sacks": 4.0,
    "def_qb_hits": 1.0, "def_pass_breakups": 1.5, "def_batted_passes": 1.5, "def_interceptions": 6.0,
    "def_int_tds": 6.0, "def_forced_fumbles": 4.0, "def_fumble_recoveries": 4.0, "def_fr_tds": 6.0,
    "def_safeties": 4.0, "def_tds": 6.0,
}
# Kicking: no registered league scores it (verified v1 2026-09-05 and v2's rules) ->
# documented house default, surfaced as mode 'default_pk', never presented as a rule.
DEFAULT_PK_POINTS = {"fg_made_0_19": 3.0, "fg_made_20_29": 3.0, "fg_made_30_39": 3.0,
                     "fg_made_40_49": 4.0, "fg_made_50p": 5.0, "pat_made": 1.0}
PK_STAT_EVENTS = {"fg_made_0_19": ["FG"], "fg_made_20_29": ["FG"], "fg_made_30_39": ["FG"],
                  "fg_made_40_49": ["FG"], "fg_made_50p": ["FG"], "pat_made": ["EP", "PAT"]}

_RANGE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$")


class Rule:
    __slots__ = ("lo", "hi", "kind", "a", "b", "text")

    def __init__(self, rng: str, points: str):
        m = _RANGE.match(rng or "")
        self.lo, self.hi = (float(m.group(1)), float(m.group(2))) if m else (-math.inf, math.inf)
        p = (points or "").strip()
        self.text = p
        if p.startswith("*"):
            self.kind, self.a = "per", float(p[1:])
        elif "/" in p:
            x, y = p.split("/", 1)
            self.kind, self.a, self.b = "incr", float(x), float(y)
        else:
            self.kind, self.a = "flat", float(p)

    def points(self, v: float) -> float:
        if v is None or not (self.lo <= v <= self.hi):
            return 0.0
        if self.kind == "per":
            return v * self.a
        if self.kind == "incr":
            # Truncate toward zero: MFL awards nothing for less than one FULL increment,
            # and nothing negative (floor(-3/100) = -1 charged Miles Sanders -115 for
            # -3 receiving yards on the first validation run).
            return int(v / self.b) * self.a if self.b and v > 0 else 0.0
        return self.a if v else 0.0   # a flat award needs the event to have happened


MFL_POSITIONS = ("QB", "RB", "WR", "TE", "DT", "DE", "LB", "CB", "S")


def catch_all_rules(conn, league_id: str) -> tuple[dict, int | None]:
    """-> ({position: {event: [Rule, ...]}}, rule season). Per position and event:
    every rule whose positions name the position, additively (see module doc)."""
    rows = conn.execute("SELECT season, positions, event, \"range\", points FROM mart_mfl_rules WHERE league_id = ?",
                        (league_id,)).fetchall()
    if not rows:
        return {}, None
    out = {}
    for pos in MFL_POSITIONS:
        ev = defaultdict(list)
        for r in rows:
            if pos in r["positions"].split("|"):
                ev[r["event"]].append(Rule(r["range"], r["points"]))
        out[pos] = dict(ev)
    return out, rows[0]["season"]


class Scorer:
    """score(row) -> fantasy points for ONE player-game row of mart_player_allowed_week.
    `rules` = one position's {event: [Rule]} (catch_all_rules(...)[position])."""

    def __init__(self, cols, rules=None, ppr=None, pk_default=False):
        self.rules, self.ppr, self.pk_default = rules, ppr, pk_default
        self.scored = {}
        for c in cols:
            if c in UNSCORABLE:
                continue
            if c in DEFAULT_PK_POINTS:
                evs = [e for e in PK_STAT_EVENTS.get(c, []) if rules and e in rules]
                if evs:
                    self.scored[c] = ("rules", rules[evs[0]])
                elif pk_default or ppr is not None:
                    self.scored[c] = ("linear", DEFAULT_PK_POINTS[c])
                continue
            if rules is not None:
                evs = [e for e in STAT_EVENTS.get(c, []) if e in rules]
                if evs:
                    self.scored[c] = ("rules", rules[evs[0]])
            elif ppr is not None and c in ppr:
                self.scored[c] = ("linear", ppr[c])

    def __call__(self, row) -> float:
        t = 0.0
        for c, (kind, spec) in self.scored.items():
            v = row[c]
            if v is None:
                continue
            if kind == "linear":
                t += v * spec
            else:
                t += sum(r.points(v) for r in spec)
        return t


def idp_calibration(conn, league_id: str, rules: dict, min_reported=20.0, min_n=30) -> tuple[dict, dict]:
    """`rules` = catch_all_rules(...)[0] (all positions).

    {group: factor}, {group: season}: median(MFL reported / catch-all predicted) per
    IDP group, newest season with >= min_n players (v1 idp_calibration's method). The
    player chain is exact keys only: MFL id -> gsis -> PFF id (mart_mfl_reported_week).
    Prediction scores each PFF player-WEEK with the catch-all rules, then sums."""
    cols = [c for c in STAT_EVENTS if c.startswith("def_")]
    scorers = {g: Scorer(cols, rules=rules.get(g, {})) for g in ("DT", "DE", "LB", "CB", "S")}
    factors, chosen = {}, {}
    seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM mart_mfl_reported_week WHERE league_id = ? "
                                          "ORDER BY season DESC", (league_id,))]
    for season in seasons:
        rep = defaultdict(float)
        for r in conn.execute("""SELECT pff_id, SUM(score) s FROM mart_mfl_reported_week
                                 WHERE league_id = ? AND season = ? AND season_type = 'REG' AND pff_id IS NOT NULL
                                 GROUP BY pff_id""", (league_id, season)):
            rep["pff:" + r["pff_id"]] = r["s"] or 0.0
        if not rep:
            continue
        weeks = {r[0] for r in conn.execute("SELECT DISTINCT week FROM mart_mfl_reported_week WHERE league_id = ? AND season = ?",
                                            (league_id, season))}
        pred, pos = defaultdict(float), {}
        for r in conn.execute(f"""SELECT * FROM mart_player_allowed_week WHERE season = ? AND season_type = 'REG'
                                  AND side = 'def' AND COALESCE(def_snaps, 0) > 0""", (season,)):
            if r["player_key"] in rep and r["week"] in weeks:
                pred[r["player_key"]] += scorers[r["position_group"]](r)
                pos[r["player_key"]] = r["position_group"]
        ratios = defaultdict(list)
        for k, g in pos.items():
            if rep[k] > min_reported and pred[k] > 0:
                ratios[g].append(rep[k] / pred[k])
        for g, xs in ratios.items():
            if g not in factors and len(xs) >= min_n:
                xs.sort()
                n = len(xs)
                factors[g] = round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 4)
                chosen[g] = season
        if all(g in factors for g in ("DT", "DE", "LB", "CB", "S")):
            break
    return factors, chosen
