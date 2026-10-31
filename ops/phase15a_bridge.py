"""Phase 15a: does PFF NCAA player_id equal the NFL pff_id for drafted defenders? Read-only; exact ids only.

Usage: python ops/phase15a_bridge.py [--list-disagreements] [--list-missing]
Population: core_nflverse_draft_picks side = 'D', season 2017-2025. A name is printed ONLY in the --list-missing reading aid;
no join or count below uses a name.
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "database" / "fdb.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

GROUP = """CASE d.position WHEN 'DE' THEN 'EDGE' WHEN 'DT' THEN 'DT' WHEN 'DL' THEN 'DT' WHEN 'NT' THEN 'DT'
  WHEN 'OLB' THEN 'LB' WHEN 'ILB' THEN 'LB' WHEN 'LB' THEN 'LB' WHEN 'CB' THEN 'CB'
  WHEN 'S' THEN 'S' WHEN 'SAF' THEN 'S' WHEN 'DB' THEN 'DB' ELSE d.position END"""

c.execute(f"""CREATE TEMP TABLE pop AS
  SELECT d.season, {GROUP} AS grp, d.position, d.gsis_id, d.pfr_player_id, d.pfr_player_name AS nm, p.pff_id,
         CAST(p.pff_id AS INTEGER) AS pid
  FROM core_nflverse_draft_picks d LEFT JOIN core_nflverse_players p ON p.gsis_id = d.gsis_id
  WHERE d.side = 'D' AND d.season BETWEEN 2017 AND 2025""")


def one(sql, *a):
    return c.execute(sql, a).fetchone()[0]


def table(title, sql, *a):
    rows = c.execute(sql, a).fetchall()
    print(f"\n{title}")
    if not rows:
        print("  (none)")
        return
    ks = rows[0].keys()
    w = [max(len(k), *(len(str(r[k])) for r in rows)) for k in ks]
    print("  " + "  ".join(k.ljust(x) for k, x in zip(ks, w)))
    for r in rows:
        print("  " + "  ".join(str(r[k]).ljust(x) for k, x in zip(ks, w)))


N = one("SELECT COUNT(*) FROM pop")
print(f"drafted defenders 2017-2025: {N}")
print(f"  with gsis_id: {one('SELECT COUNT(*) FROM pop WHERE gsis_id IS NOT NULL')}; "
      f"with players.pff_id: {one('SELECT COUNT(*) FROM pop WHERE pid IS NOT NULL')}")

c.execute("""CREATE TEMP TABLE flags AS SELECT p.*,
  EXISTS (SELECT 1 FROM core_pff_ncaa_defense_season n WHERE n.player_id = p.pid) AS any_def,
  EXISTS (SELECT 1 FROM core_pff_ncaa_defense_season n WHERE n.player_id = p.pid AND n.season = p.season - 1) AS prev_def,
  EXISTS (SELECT 1 FROM core_pff_ncaa_pass_rush_season n WHERE n.player_id = p.pid AND n.season = p.season - 1) AS prev_pr,
  EXISTS (SELECT 1 FROM core_pff_ncaa_pass_rush_season n WHERE n.player_id = p.pid) AS any_pr
  FROM pop p""")
SUMS = """COUNT(*) drafted, SUM(pid IS NOT NULL) has_pff_id, SUM(any_def) ncaa_any, SUM(prev_def) ncaa_prev_season,
  SUM(prev_def AND prev_pr) both_facets_prev, ROUND(100.0*SUM(any_def)/COUNT(*),1) pct_any, ROUND(100.0*SUM(prev_def)/COUNT(*),1) pct_prev"""
table("by draft class", f"SELECT season, {SUMS} FROM flags GROUP BY season ORDER BY season")
table("by position group", f"SELECT grp, {SUMS} FROM flags GROUP BY grp ORDER BY grp")
table("ALL", f"SELECT 'all' k, {SUMS} FROM flags")
table("by class x group", """SELECT season, grp, COUNT(*) drafted, SUM(any_def) ncaa_any, SUM(prev_def) prev_season
  FROM flags GROUP BY season, grp ORDER BY season, grp""")

# exact-key validation: PFF NCAA draft_season vs the actual draft year
c.execute("""CREATE TEMP TABLE ds AS SELECT f.gsis_id, f.season draft_year, f.pid, n.season ncaa_season, n.draft_season, n.eligible_season
  FROM flags f JOIN core_pff_ncaa_defense_season n ON n.player_id = f.pid""")
table("draft_season validation, per joined NCAA row", """SELECT
  SUM(draft_season = draft_year) agree, SUM(draft_season IS NOT NULL AND draft_season != draft_year) disagree,
  SUM(draft_season IS NULL) unset, COUNT(*) total_rows FROM ds""")
table("draft_season validation, per player (all NCAA rows)", """SELECT SUM(a > 0 AND d = 0) agree_only, SUM(d > 0) any_disagree,
  SUM(a = 0 AND d = 0) never_set, COUNT(*) players FROM (SELECT gsis_id, SUM(draft_season = draft_year) a,
  SUM(draft_season IS NOT NULL AND draft_season != draft_year) d FROM ds GROUP BY gsis_id)""")
table("draft_season validation, the season before the draft (the model's feature season)", """SELECT
  SUM(draft_season = draft_year) agree, SUM(draft_season IS NOT NULL AND draft_season != draft_year) disagree,
  SUM(draft_season IS NULL) unset, COUNT(*) players FROM ds WHERE ncaa_season = draft_year - 1""")
table("disagreeing rows: draft_season minus draft_year", """SELECT draft_season - draft_year AS diff, COUNT(*) total_rows,
  COUNT(DISTINCT gsis_id) players FROM ds WHERE draft_season IS NOT NULL AND draft_season != draft_year GROUP BY 1 ORDER BY 2 DESC""")
if "--list-disagreements" in sys.argv:
    table("each disagreement", """SELECT gsis_id, pid pff_id, ncaa_season, draft_season, draft_year
      FROM ds WHERE draft_season IS NOT NULL AND draft_season != draft_year ORDER BY gsis_id, ncaa_season""")

# reverse: NCAA ids (2016+) that equal an NFL pff_id of someone who is not a drafted defender 2017-2025
table("reverse check: distinct NCAA defense player_ids equal to an NFL pff_id, by who the NFL human is", """
  WITH n AS (SELECT DISTINCT player_id FROM core_pff_ncaa_defense_season),
  m AS (SELECT n.player_id, p.gsis_id FROM n JOIN core_nflverse_players p ON CAST(p.pff_id AS INTEGER) = n.player_id)
  SELECT CASE WHEN m.gsis_id IN (SELECT gsis_id FROM pop WHERE gsis_id IS NOT NULL) THEN '1 drafted defender 2017-25'
              WHEN m.gsis_id IN (SELECT gsis_id FROM core_nflverse_draft_picks WHERE gsis_id IS NOT NULL) THEN '2 drafted, other side or year'
              ELSE '3 not in draft_picks' END AS nfl_human, COUNT(*) ncaa_ids FROM m GROUP BY 1 ORDER BY 1""")
table("reverse check, group 3 (not in draft_picks): PFF draft_season minus the NFL human's players.rookie_season (0 = same entry class; PFF sets draft_season for undrafted players too)", """
  SELECT n.ds - p.rookie_season AS diff, COUNT(*) ncaa_ids
  FROM (SELECT player_id, MAX(draft_season) ds FROM core_pff_ncaa_defense_season GROUP BY player_id) n
  JOIN core_nflverse_players p ON CAST(p.pff_id AS INTEGER) = n.player_id
  WHERE p.gsis_id NOT IN (SELECT gsis_id FROM core_nflverse_draft_picks WHERE gsis_id IS NOT NULL) GROUP BY 1 ORDER BY 2 DESC""")
table("reverse check, group 2 (drafted, other side or year): PFF draft_season minus draft_picks.season (expect only 0)", """
  SELECT n.ds - d.season AS diff, COUNT(*) ncaa_ids
  FROM (SELECT player_id, MAX(draft_season) ds FROM core_pff_ncaa_defense_season GROUP BY player_id) n
  JOIN core_nflverse_players p ON CAST(p.pff_id AS INTEGER) = n.player_id JOIN core_nflverse_draft_picks d ON d.gsis_id = p.gsis_id
  WHERE NOT (d.side = 'D' AND d.season BETWEEN 2017 AND 2025) GROUP BY 1 ORDER BY 2 DESC""")
table("NFL humans reached by more than one NCAA id", """
  SELECT COUNT(*) gsis_with_multiple_ncaa_ids FROM (SELECT p.gsis_id FROM (SELECT DISTINCT player_id FROM core_pff_ncaa_defense_season) n
  JOIN core_nflverse_players p ON CAST(p.pff_id AS INTEGER) = n.player_id GROUP BY p.gsis_id HAVING COUNT(*) > 1)""")

# combine, by exact pfr_id
c.execute("""CREATE TEMP TABLE cb AS SELECT f.season, f.grp, f.pfr_player_id, cm.pfr_id IS NOT NULL AS has_combine, cm.forty
  FROM flags f LEFT JOIN core_nflverse_combine cm ON cm.pfr_id = f.pfr_player_id AND cm.season = f.season AND cm.draft_year = f.season""")
table("combine join by pfr_id (+ 40-yd present), by class", """SELECT season, COUNT(*) drafted, SUM(has_combine) combine,
  ROUND(100.0*SUM(has_combine)/COUNT(*),1) pct_combine, SUM(forty IS NOT NULL) forty, ROUND(100.0*SUM(forty IS NOT NULL)/COUNT(*),1) pct_forty
  FROM cb GROUP BY season ORDER BY season""")
table("combine, ALL", """SELECT COUNT(*) drafted, SUM(has_combine) combine, ROUND(100.0*SUM(has_combine)/COUNT(*),1) pct_combine,
  SUM(forty IS NOT NULL) forty, ROUND(100.0*SUM(forty IS NOT NULL)/COUNT(*),1) pct_forty FROM cb""")
table("combine by position group", """SELECT grp, COUNT(*) drafted, ROUND(100.0*SUM(has_combine)/COUNT(*),1) pct_combine,
  ROUND(100.0*SUM(forty IS NOT NULL)/COUNT(*),1) pct_forty FROM cb GROUP BY grp ORDER BY grp""")

table("drafted defenders with no NCAA defense row for any season, by class", """SELECT season, COUNT(*) missing, SUM(pid IS NULL) no_pff_id
  FROM flags WHERE NOT any_def GROUP BY season ORDER BY season""")
if "--list-missing" in sys.argv:
    table("missing, one per row (reading aid only; the name selects nothing)", """SELECT season, grp, position, gsis_id, pff_id,
      nm AS reading_aid_name FROM flags WHERE NOT any_def ORDER BY season, grp""")
