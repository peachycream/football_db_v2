"""Identity builder (REBUILD_DESIGN §3): core identity sources -> players,
player_ids, identity_quarantine. Deterministic; fully rebuilt in one transaction.

Precedence, strongest first. A weaker source can ADD a mapping nobody else made;
it can never override a stronger one, and a disagreement is quarantined:
  1. nflverse players.csv         (source_native)  pff, pfr, espn, otc, nfl, esb, smart
  2. nflverse weekly rosters      (source_native)  sleeper, sportradar, yahoo, rotowire,
                                                   fantasy_data, and pff/pfr/espn fills
  3. DynastyProcess db_playerids  (id_map)         mfl, and sleeper fills; every row
                                                   must pass the negative name check
  4. identity_overrides.csv       (manual)         last word, reason required

Why 1 beats 2: nflverse's own 2016 weekly roster gives Damaris Johnson the
pff/pfr ids of Dennis Johnson; players.csv has them right.
Why 3 needs a name check: db_playerids puts gsis 00-0031320 on both 'Kevin
Smith' and 'Fred Williams', and Bobby McCray's gsis on punter Jake Schum.
"""
import csv
from collections import defaultdict

from . import config, traps
from .names import name_disagrees, surname_agrees

# nflverse's own position -> position_group mapping, as observed in players.csv
# (2024+). Used only for roster-only people, who arrive without a group.
POSITION_GROUP = {
    "CB": "DB", "DB": "DB", "FS": "DB", "S": "DB", "SS": "DB", "SAF": "DB",
    "DE": "DL", "DL": "DL", "DT": "DL", "NT": "DL",
    "ILB": "LB", "LB": "LB", "MLB": "LB", "OLB": "LB",
    "C": "OL", "G": "OL", "OL": "OL", "OT": "OL", "T": "OL", "OG": "OL",
    "QB": "QB", "FB": "RB", "RB": "RB", "HB": "RB", "TE": "TE", "WR": "WR",
    "K": "SPEC", "LS": "SPEC", "P": "SPEC",
}

NFLVERSE_PLAYER_IDS = ["pff", "pfr", "espn", "otc", "nfl", "esb", "smart"]
ROSTER_IDS = ["sleeper", "sportradar", "yahoo", "rotowire", "fantasy_data", "pff", "pfr", "espn"]
DP_IDS = ["mfl", "sleeper"]
OVERRIDES_PATH = config.ROOT / "identity_overrides.csv"


class Builder:
    def __init__(self, conn):
        self.conn = conn
        self.ids: dict[tuple[str, str], tuple[str, str, str]] = {}   # (source, sid) -> (gsis, method, evidence)
        self.quarantine: list[tuple] = []
        self.people: dict[str, dict] = {}
        self.by_gsis: dict[tuple[str, str], tuple[str, str]] = {}   # (source, gsis) -> (sid, evidence)

    def refuse(self, source, sid, gsis, name, evidence, reason):
        self.quarantine.append((source, sid, gsis, name, evidence, reason))

    def claim(self, source, sid, gsis, method, evidence, name=None) -> bool:
        """Add a mapping unless it conflicts with a stronger one. -> accepted?"""
        key = (source, sid)
        have = self.ids.get(key)
        if have and have[0] != gsis:
            self.refuse(source, sid, gsis, name, evidence, f"conflicts with {have[2]} (-> {have[0]})")
            return False
        if gsis not in self.people:
            self.refuse(source, sid, gsis, name, evidence, "claimed gsis_id is not a known player")
            return False
        other = self.by_gsis.get((source, gsis))
        if other and other[0] != sid:  # one human, one id per source; the stronger claim came first
            self.refuse(source, sid, gsis, name, evidence, f"gsis_id already has {source} id {other[0]} from {other[1]}")
            return False
        if not have:
            self.ids[key] = (gsis, method, evidence)
            self.by_gsis[(source, gsis)] = (sid, evidence)
        return True

    # -- 1 -----------------------------------------------------------------
    def from_nflverse_players(self):
        rows = self.conn.execute("SELECT * FROM core_nflverse_players").fetchall()
        for r in rows:
            self.people[r["gsis_id"]] = {
                "gsis_id": r["gsis_id"], "display_name": r["display_name"], "first_name": r["first_name"],
                "last_name": r["last_name"], "common_first_name": r["common_first_name"],
                "football_name": r["football_name"], "birth_date": r["birth_date"], "position": r["position"],
                "position_group": r["position_group"], "height": r["height"], "weight": r["weight"],
                "college": r["college_name"], "rookie_season": r["rookie_season"], "last_season": r["last_season"],
                "latest_team": r["latest_team"], "draft_year": r["draft_year"], "draft_round": r["draft_round"],
                "draft_pick_overall": r["draft_pick"], "players_source": "nflverse_players"}
        for src in NFLVERSE_PLAYER_IDS:
            owners = defaultdict(set)
            for r in rows:
                if r[f"{src}_id"]:
                    owners[r[f"{src}_id"]].add(r["gsis_id"])
            for sid, gs in owners.items():
                if len(gs) > 1:  # e.g. one esb_id and one smart_id each sit on two gsis_ids
                    for g in sorted(gs):
                        self.refuse(src, sid, g, None, "nflverse players.csv", f"source id on {len(gs)} gsis_ids")
                else:
                    self.claim(src, sid, next(iter(gs)), "source_native", "nflverse players.csv")

    # -- 2 -----------------------------------------------------------------
    def from_rosters(self):
        latest = self.conn.execute("""
            SELECT r.* FROM core_rosters_weekly r
            JOIN (SELECT gsis_id, MAX(season * 100 + week) k FROM core_rosters_weekly
                  WHERE gsis_id IS NOT NULL GROUP BY gsis_id) m
              ON m.gsis_id = r.gsis_id AND r.season * 100 + r.week = m.k""").fetchall()
        for r in latest:  # new signings not yet in players.csv
            if r["gsis_id"] not in self.people:
                self.people[r["gsis_id"]] = {
                    "gsis_id": r["gsis_id"], "display_name": r["full_name"], "first_name": r["first_name"],
                    "last_name": r["last_name"], "common_first_name": None, "football_name": r["football_name"],
                    "birth_date": r["birth_date"], "position": r["position"],
                    "position_group": POSITION_GROUP.get(r["position"]),
                    "height": r["height"], "weight": r["weight"], "college": r["college"],
                    "rookie_season": r["rookie_year"], "last_season": r["season"], "latest_team": r["team"],
                    "draft_year": None, "draft_round": None, "draft_pick_overall": r["draft_number"],
                    "players_source": "rosters_weekly"}
        for src in ROSTER_IDS:
            pairs = self.conn.execute(f"""SELECT {src}_id sid, gsis_id, MIN(full_name) name FROM core_rosters_weekly
                                          WHERE {src}_id IS NOT NULL AND gsis_id IS NOT NULL
                                          GROUP BY {src}_id, gsis_id""").fetchall()
            owners = defaultdict(list)
            for p in pairs:
                owners[p["sid"]].append(p)
            for sid, ps in sorted(owners.items()):
                if len(ps) > 1:
                    for p in ps:
                        self.refuse(src, sid, p["gsis_id"], p["name"], "nflverse weekly rosters", f"roster id on {len(ps)} gsis_ids")
                    continue
                p = ps[0]
                self.claim(src, sid, p["gsis_id"], "source_native", "nflverse weekly rosters", p["name"])

    # -- 3 -----------------------------------------------------------------
    def from_dp(self):
        rows = self.conn.execute("SELECT * FROM core_dp_playerids WHERE gsis_id IS NOT NULL").fetchall()
        passed = []
        for r in rows:
            person = self.people.get(r["gsis_id"])
            if person is None:
                self.refuse("mfl", r["mfl_id"], r["gsis_id"], r["name"], "dynastyprocess", "claimed gsis_id is not a known player")
            elif name_disagrees(r["name"], person):
                # Nickname rule: surname agrees and the exact birth date matches (an
                # independent biographical fact), so a first-initial mismatch is a
                # nickname (Drew/Andrew Ogletree, Zeke/Ezekiel Turner), not a different man.
                if (surname_agrees(r["name"], person) and r["birthdate"] and person["birth_date"]
                        and r["birthdate"] == person["birth_date"]):
                    passed.append(r)
                    continue
                self.refuse("mfl", r["mfl_id"], r["gsis_id"], r["name"], "dynastyprocess",
                            f"name disagrees with nflverse ({person['display_name']})")
            else:
                passed.append(r)
        by_gsis = defaultdict(list)
        for r in passed:
            by_gsis[r["gsis_id"]].append(r)
        for g, rs in sorted(by_gsis.items()):
            if len(rs) > 1:  # two MFL ids on one human, both name-consistent: cannot tell which is real
                for r in rs:
                    self.refuse("mfl", r["mfl_id"], g, r["name"], "dynastyprocess", f"gsis_id claimed by {len(rs)} mfl_ids")
                continue
            r = rs[0]
            self.claim("mfl", r["mfl_id"], g, "id_map", "dynastyprocess", r["name"])
            if r["sleeper_id"] and ("sleeper", r["sleeper_id"]) not in self.ids:
                self.claim("sleeper", r["sleeper_id"], g, "id_map", "dynastyprocess", r["name"])

    # -- 4 -----------------------------------------------------------------
    def from_overrides(self):
        if not OVERRIDES_PATH.exists():
            return
        with open(OVERRIDES_PATH, newline="", encoding="utf-8") as f:
            for o in csv.DictReader(f):
                if not o.get("reason"):
                    raise ValueError(f"identity_overrides.csv row without a reason: {o}")
                if o["gsis_id"] not in self.people:
                    raise ValueError(f"override names unknown gsis_id: {o}")
                old = self.ids.get((o["source"], o["source_id"]))
                if old:
                    self.by_gsis.pop((o["source"], old[0]), None)
                prev = self.by_gsis.get((o["source"], o["gsis_id"]))
                if prev:  # the override replaces whatever id this human had for the source
                    self.ids.pop((o["source"], prev[0]), None)
                self.ids[(o["source"], o["source_id"])] = (o["gsis_id"], "manual", f"override: {o['reason']}")
                self.by_gsis[(o["source"], o["gsis_id"])] = (o["source_id"], "override")
                self.quarantine = [q for q in self.quarantine if (q[0], q[1]) != (o["source"], o["source_id"])]

    def write(self):
        c = self.conn
        cols = ["gsis_id", "display_name", "first_name", "last_name", "birth_date", "position", "position_group",
                "height", "weight", "college", "rookie_season", "last_season", "latest_team", "draft_year",
                "draft_round", "draft_pick_overall", "players_source"]
        c.execute("DELETE FROM player_ids")
        c.execute("DELETE FROM identity_quarantine")
        c.execute("DELETE FROM players")
        c.executemany(f"INSERT INTO players ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                      [[p[k] for k in cols] for _, p in sorted(self.people.items())])
        c.executemany("INSERT INTO player_ids (source, source_id, gsis_id, method, evidence) VALUES (?,?,?,?,?)",
                      [(s, sid, *v) for (s, sid), v in sorted(self.ids.items())])
        c.executemany("INSERT INTO identity_quarantine VALUES (?,?,?,?,?,?)", sorted(self.quarantine, key=repr))


STRICT_SOURCES = ("pff", "pfr", "mfl", "sleeper", "espn")


def checks(conn) -> list[str]:
    fails = []
    for src in STRICT_SOURCES:
        n = conn.execute("""SELECT COUNT(*) FROM (SELECT gsis_id FROM player_ids WHERE source = ?
                            GROUP BY gsis_id HAVING COUNT(*) > 1)""", (src,)).fetchone()[0]
        if n:
            fails.append(f"{src}: {n} gsis_ids carry more than one {src} id")
    return fails


def build(conn, apply: bool = True) -> dict:
    b = Builder(conn)
    conn.execute("BEGIN")
    try:
        b.from_nflverse_players()
        b.from_rosters()
        b.from_dp()
        b.from_overrides()
        b.write()
        fails = checks(conn) + traps.check(conn)
        report = {"players": len(b.people), "player_ids": len(b.ids), "quarantined": len(b.quarantine),
                  "failures": fails, "applied": False}
        if fails or not apply:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")
            report["applied"] = True
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return report
