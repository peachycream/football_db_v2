"""`fdb reconcile`: cross-source agreement checks (Phase 2 gate, re-runnable any time).

Each check compares two INDEPENDENT paths to the same number. Agreement is
evidence both are loaded right; a column mapped wrongly (v1 rule 13a) shows up
as a disagreement even though every load "succeeded"."""


def _pct(a, b):
    return 100.0 * a / b if b else float("nan")


def run(conn, season: int) -> list[tuple[str, str, bool]]:
    out = []
    q = lambda sql, *p: conn.execute(sql, p).fetchall()

    # 1. player_stats vs pbp, per player-game: targets, receptions, receiving yards, carries
    rows = q("""WITH pb AS (
                  SELECT game_id, receiver_player_id pid, SUM(pass_attempt=1 AND sack=0) tgt,
                         SUM(complete_pass) rec, COALESCE(SUM(CASE WHEN complete_pass=1 THEN yards_gained END), 0) yds
                  FROM core_pbp WHERE season=? AND receiver_player_id IS NOT NULL AND two_point_attempt=0
                  GROUP BY 1,2)
                SELECT COUNT(*), SUM(s.targets=pb.tgt), SUM(s.receptions=pb.rec), SUM(s.receiving_yards=pb.yds)
                FROM pb JOIN core_player_stats s ON s.game_id=pb.game_id AND s.player_id=pb.pid""", season)
    n, t, r, y = rows[0]
    # yards: pbp yards_gained differs from credited receiving yards on laterals/fumbles (~0.5%)
    out.append((f"{season} player_stats vs pbp targets / rec / rec yds (player-games)",
                f"{n}: {_pct(t,n):.1f}% / {_pct(r,n):.1f}% / {_pct(y,n):.1f}% exact", n > 0 and min(t, r) / n >= 0.99 and y / n >= 0.98))
    n, c = q("""WITH pb AS (SELECT game_id, rusher_player_id pid, SUM(rush_attempt=1) car FROM core_pbp
                WHERE season=? AND rusher_player_id IS NOT NULL AND two_point_attempt=0 GROUP BY 1,2)
                SELECT COUNT(*), SUM(s.carries=pb.car) FROM pb JOIN core_player_stats s
                ON s.game_id=pb.game_id AND s.player_id=pb.pid""", season)[0]
    out.append((f"{season} player_stats vs pbp carries", f"{n}: {_pct(c,n):.1f}% exact", n > 0 and c / n >= 0.97))

    # 2. NGS passing attempts vs player_stats attempts, per player-week
    n, a = q("""SELECT COUNT(*), SUM(g.attempts = s.att) FROM core_ngs_passing g
                JOIN (SELECT player_id, season, season_type, week, SUM(attempts) att FROM core_player_stats
                      WHERE season=? GROUP BY 1,2,3,4) s
                  ON s.player_id=g.player_gsis_id AND s.season=g.season AND s.season_type=g.season_type AND s.week=g.schedule_week
                WHERE g.season=?""", season, season)[0]
    out.append((f"{season} NGS pass attempts vs player_stats (player-weeks)", f"{n}: {_pct(a,n):.1f}% exact", n > 0 and a / n >= 0.95))

    # 3. ff_opportunity receptions vs player_stats, per player-game
    n, a = q("""SELECT COUNT(*), SUM(f.receptions = s.receptions) FROM core_ff_opportunity f
                JOIN core_player_stats s ON s.game_id=f.game_id AND s.player_id=f.player_id
                WHERE f.season=? AND f.receptions IS NOT NULL""", season)[0]
    out.append((f"{season} ff_opportunity receptions vs player_stats", f"{n}: {_pct(a,n):.1f}% exact", n > 0 and a / n >= 0.95))

    # 4. snap counts: team offense snaps (max player per team-game) vs pbp scrimmage plays incl. penalties
    n, a = q("""WITH sc AS (SELECT game_id, team, MAX(offense_snaps) snaps FROM core_snap_counts WHERE season=? GROUP BY 1,2),
                     pb AS (SELECT game_id, posteam team, SUM(play=1) plays FROM core_pbp WHERE season=? GROUP BY 1,2)
                SELECT COUNT(*), SUM(ABS(sc.snaps - pb.plays) <= 0.10 * pb.plays) FROM sc
                JOIN team_aliases a ON a.abbr = sc.team AND ? BETWEEN a.season_from AND a.season_to
                JOIN team_aliases b ON b.team = a.team AND ? BETWEEN b.season_from AND b.season_to
                JOIN pb ON pb.game_id = sc.game_id AND pb.team = b.abbr""", season, season, season, season)[0]
    out.append((f"{season} team offense snaps (PFR) vs pbp plays, within 10%", f"{n}: {_pct(a,n):.1f}%", n > 0 and a / n >= 0.90))

    # 5. identity resolution of every player key
    for label, sql in [
        ("player_stats.player_id", "SELECT COUNT(*), SUM(p.gsis_id IS NOT NULL) FROM core_player_stats x LEFT JOIN players p ON p.gsis_id=x.player_id WHERE x.season=?"),
        ("snap_counts.pfr_player_id", "SELECT COUNT(*), SUM(i.gsis_id IS NOT NULL) FROM core_snap_counts x LEFT JOIN player_ids i ON i.source='pfr' AND i.source_id=x.pfr_player_id WHERE x.season=?"),
        ("pbp.passer/rusher/receiver", """SELECT COUNT(*), SUM(p.gsis_id IS NOT NULL) FROM (
             SELECT passer_player_id id FROM core_pbp WHERE season=? AND passer_player_id IS NOT NULL
             UNION ALL SELECT rusher_player_id FROM core_pbp WHERE season=?1 AND rusher_player_id IS NOT NULL
             UNION ALL SELECT receiver_player_id FROM core_pbp WHERE season=?1 AND receiver_player_id IS NOT NULL) x
             LEFT JOIN players p ON p.gsis_id = x.id"""),
        ("pbp tacklers (solo_tackle_1)", "SELECT COUNT(*), SUM(p.gsis_id IS NOT NULL) FROM core_pbp x LEFT JOIN players p ON p.gsis_id=x.solo_tackle_1_player_id WHERE x.season=? AND x.solo_tackle_1_player_id IS NOT NULL"),
        ("ngs_receiving.player_gsis_id", "SELECT COUNT(*), SUM(p.gsis_id IS NOT NULL) FROM core_ngs_receiving x LEFT JOIN players p ON p.gsis_id=x.player_gsis_id WHERE x.season=?"),
        # NULL player_id = ffopportunity's unattributed team bucket (one per team-game), not a player
        ("ff_opportunity.player_id", "SELECT COUNT(*), SUM(p.gsis_id IS NOT NULL) FROM core_ff_opportunity x LEFT JOIN players p ON p.gsis_id=x.player_id WHERE x.season=? AND x.player_id IS NOT NULL"),
    ]:
        n, ok = conn.execute(sql.replace("?1", "?"), (season,) * sql.count("?")).fetchone()
        out.append((f"{season} resolves: {label}", f"{ok}/{n} = {_pct(ok,n):.2f}%", n == 0 or ok / n >= 0.99))

    from . import reconcile_pff  # Phase 4: only once PFF rows exist for the season
    out.extend(reconcile_pff.run(conn, season))

    from . import participation  # Phase 5: the nflverse/FTN participation seam
    if conn.execute("SELECT 1 FROM core_ftn_participation WHERE season = ? LIMIT 1", (season,)).fetchone():
        if season < participation.FTN_FROM:
            out.extend(participation.seam_test(conn, seasons=(season,)))
        else:
            out.extend(participation.live_checks(conn, season))
    return out
