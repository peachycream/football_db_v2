"""Builder `fantasy.config`: config/my_franchises.toml -> my_franchises, plus the
ownership report (every unresolved roster slot is counted by category, so a
dropped id cannot be silent)."""
from . import leagues


def build(conn) -> dict:
    rows = [(lg.platform, lg.league_id, s, lg.name, lg.my_franchise) for lg in leagues.load() for s in lg.seasons]
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM my_franchises")
        conn.executemany("INSERT INTO my_franchises (platform, league_id, season, name, my_franchise) VALUES (?,?,?,?,?)", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    fails = []
    # my franchise must exist in every league we hold a roster snapshot for
    for r in conn.execute("""SELECT o.platform, o.league_id, o.season, m.my_franchise FROM
                               (SELECT DISTINCT platform, league_id, season FROM mart_roster_ownership) o
                             LEFT JOIN my_franchises m USING (platform, league_id, season)""").fetchall():
        if r["my_franchise"] is None:
            fails.append(f"{r['platform']}:{r['league_id']} {r['season']} has rosters but no entry in my_franchises.toml")
        elif not conn.execute("SELECT 1 FROM mart_roster_ownership WHERE platform = ? AND league_id = ? AND season = ? AND is_mine = 1",
                              (r["platform"], r["league_id"], r["season"])).fetchone():
            fails.append(f"{r['platform']}:{r['league_id']} {r['season']}: my franchise {r['my_franchise']} has no roster rows")
    # 0 silently dropped slots: the mart's joins must keep every latest-snapshot core row.
    for platform, table in (("mfl", "core_mfl_rosters"), ("sleeper", "core_sleeper_rosters")):
        core = dict(((r[0], r[1]), r[2]) for r in conn.execute(f"""
            SELECT t.season, t.league_id, COUNT(*) FROM {table} t JOIN
              (SELECT season, league_id, MAX(snapshot_at) s FROM {table} GROUP BY 1, 2) x
              ON x.season = t.season AND x.league_id = t.league_id AND x.s = t.snapshot_at GROUP BY 1, 2"""))
        mart = dict(((r[0], r[1]), r[2]) for r in conn.execute(
            "SELECT season, league_id, COUNT(*) FROM mart_roster_ownership WHERE platform = ? GROUP BY 1, 2", (platform,)))
        for k in sorted(set(core) | set(mart)):
            if core.get(k, 0) != mart.get(k, 0):
                fails.append(f"{platform}:{k[1]} {k[0]}: latest snapshot has {core.get(k, 0)} slots, "
                             f"mart_roster_ownership {mart.get(k, 0)} (a join dropped rows)")
    slots = conn.execute("SELECT COUNT(*) FROM mart_roster_ownership").fetchone()[0]
    unres = dict(conn.execute("SELECT category, COUNT(*) FROM mart_roster_unresolved GROUP BY category").fetchall())
    summary = f"{len(rows)} league-seasons; {slots} roster slots, unresolved " + (
        ", ".join(f"{k} {v}" for k, v in sorted(unres.items())) or "none")
    return {"failures": fails, "summary": summary, "unresolved": unres}
