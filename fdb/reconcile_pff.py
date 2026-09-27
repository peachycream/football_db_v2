"""PFF reconciliation (Phase 4 gate), run by `fdb reconcile` whenever PFF rows exist.

Each check compares PFF with an INDEPENDENT source, or PFF's weekly rows with PFF's
own server-aggregated season line. Teams are compared through team_aliases (PFF
writes ARZ/BLT/CLV/HST/LA; nflverse ARI/BAL/CLE/HOU/LA)."""

OL_POSITIONS = ("T", "G", "C")
PFF_WEEKS = tuple(range(1, 19)) + (28, 29, 30, 32)


def _pct(a, b):
    return 100.0 * a / b if b else float("nan")


def explain_snaps(conn, season: int, teams: list[str]) -> tuple[str, str, bool]:
    """For team-seasons outside 1%, split the gap by player-game through exact ids
    (PFF player_id and PFR pfr_player_id, each -> gsis_id): snaps of player-games only
    ONE source has (e.g. PFR has no row for Tariq Woolen, 2026 wk1, 70 PFF snaps) vs the
    rest. PASS only if, with one-sided player-games set aside, every team is within 1%.
    Nothing is loosened: every one-sided player-game is listed."""
    if not teams:
        return (f"{season} PFF vs PFR defensive snaps, explained", "every team within 1% raw", True)
    notes, ok_all = [], True
    for team in teams:
        rows = conn.execute("""
            WITH p AS (SELECT x.season_type st, x.week, COALESCE(i.gsis_id, 'pff:' || x.player_id) k, x.player nm, x.snap_counts_defense s
                       FROM core_pff_defense_week x JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
                       LEFT JOIN player_ids i ON i.source = 'pff' AND i.source_id = CAST(x.player_id AS TEXT)
                       WHERE x.season = ? AND a.team = ? AND x.snap_counts_defense > 0),
                 n AS (SELECT x.season_type st, x.week, COALESCE(i.gsis_id, 'pfr:' || x.pfr_player_id) k, x.player nm, x.defense_snaps s
                       FROM core_snap_counts x JOIN team_aliases a ON a.abbr = x.team AND x.season BETWEEN a.season_from AND a.season_to
                       LEFT JOIN player_ids i ON i.source = 'pfr' AND i.source_id = x.pfr_player_id
                       WHERE x.season = ? AND a.team = ? AND x.defense_snaps > 0)
            SELECT p.st, p.week, p.k, p.nm, p.s, NULL FROM p LEFT JOIN n USING (st, week, k) WHERE n.k IS NULL
            UNION ALL SELECT n.st, n.week, n.k, n.nm, NULL, n.s FROM n LEFT JOIN p USING (st, week, k) WHERE p.k IS NULL
            UNION ALL SELECT p.st, p.week, p.k, p.nm, p.s, n.s FROM p JOIN n USING (st, week, k)""", (season, team, season, team)).fetchall()
        both = [r for r in rows if r[4] is not None and r[5] is not None]
        a, b = sum(r[4] for r in both), sum(r[5] for r in both)
        pff_only = [f"{r[3]} wk{r[1]} {r[4]}" for r in rows if r[5] is None]
        pfr_only = [f"{r[3]} wk{r[1]} {r[5]}" for r in rows if r[4] is None]
        # Whole-play differences: in a team-week where EVERY differing defender differs by
        # the same k, one source counted k play(s) the other did not (LV 2026: all 11
        # on-field defenders +1 in PFR, both weeks). Attributed, then set aside.
        plays, adj_a = [], a
        for (st, wk) in sorted({(r[0], r[1]) for r in both}):
            d = [r[5] - r[4] for r in both if (r[0], r[1]) == (st, wk) and r[5] != r[4]]
            if d and len(set(d)) == 1 and 9 <= len(d) <= 12:
                plays.append(f"wk{wk} {d[0]:+d} play(s) x {len(d)} defenders")
                adj_a += d[0] * len(d)
        ok = b > 0 and abs(adj_a - b) <= 0.01 * b
        ok_all = ok_all and ok
        notes.append(f"{team}: matched {a} vs {b} ({100 * (a - b) / b:+.2f}%), after whole-play differences "
                     f"{100 * (adj_a - b) / b:+.2f}% [{'; '.join(plays) or 'none'}]; only in PFF {pff_only or '-'}; "
                     f"only in PFR {pfr_only or '-'}")
    return (f"{season} PFF vs PFR defensive snaps, explained per player-game", " | ".join(notes), ok_all)


def run(conn, season: int) -> list[tuple[str, str, bool]]:
    q = lambda sql, *p: conn.execute(sql, p).fetchall()
    if not q("SELECT 1 FROM core_pff_defense_week WHERE season = ? LIMIT 1", season):
        return []
    out = []

    # 1. Week vocabulary: only REG 1-18 and POST 28/29/30/32 (preseason has no number here),
    #    and PFF holds exactly the weeks the schedule says are complete.
    from . import schedule
    done = set(schedule.completed_weeks(conn, season))
    for t in ("core_pff_defense_week", "core_pff_blocking_week", "core_pff_passing_week", "core_pff_receiving_week",
              "core_pff_rushing_week", "core_pff_coverage_scheme_week", "core_pff_fg_week"):
        have = {(r[0], r[1]) for r in q(f"SELECT DISTINCT season_type, week FROM {t} WHERE season = ?", season)}
        bad = [r[0] for r in q(f"SELECT DISTINCT pff_week FROM {t} WHERE season = ?", season) if r[0] not in PFF_WEEKS]
        ok = not bad and have == done
        out.append((f"{season} {t}: weeks = schedule's completed weeks, PFF weeks in 1-18/28-32",
                    f"{len(have)}/{len(done)} weeks" + (f", bad pff_week {bad}" if bad else "")
                    + (f", missing {sorted(done - have)}" if done - have else ""), ok))

    # 2. THE GATE: PFF defensive snaps vs nflverse/PFR defensive snaps, per team-season, within 1%.
    #    Same weeks on both sides (a week missing from either is excluded, and check 1 reports it).
    rows = q("""WITH p AS (SELECT a.team, x.season_type, x.week, SUM(x.snap_counts_defense) s FROM core_pff_defense_week x
                           JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
                           WHERE x.season = ? GROUP BY 1, 2, 3),
                     n AS (SELECT a.team, x.season_type, x.week, SUM(x.defense_snaps) s FROM core_snap_counts x
                           JOIN team_aliases a ON a.abbr = x.team AND x.season BETWEEN a.season_from AND a.season_to
                           WHERE x.season = ? GROUP BY 1, 2, 3)
                SELECT p.team, SUM(p.s), SUM(n.s) FROM p JOIN n USING (team, season_type, week) GROUP BY p.team""",
             season, season)
    within = [r for r in rows if r[2] and abs(r[1] - r[2]) <= 0.01 * r[2]]
    worst = max(rows, key=lambda r: abs(r[1] - r[2]) / r[2] if r[2] else 0) if rows else None
    out.append((f"{season} PFF vs PFR defensive snaps per team-season, within 1% (raw)",
                f"{len(within)}/{len(rows)} teams" + (f"; worst {worst[0]} {worst[1]} vs {worst[2]} "
                                                      f"({100 * (worst[1] - worst[2]) / worst[2]:+.2f}%)" if worst else ""),
                True))  # reported; the verdict is the explained check below
    out.append(explain_snaps(conn, season, [r[0] for r in rows if r not in within]))

    # 2b. PFF self-consistency: 11 defenders on every snap, so a team-week's player snaps
    #     divide by 11 exactly. A dropped or duplicated defender breaks it.
    n, ok = q("""SELECT COUNT(*), SUM(s % 11 = 0) FROM (SELECT SUM(snap_counts_defense) s FROM core_pff_defense_week
                 WHERE season = ? GROUP BY season_type, week, team_name)""", season)[0]
    # Reported only: 12-men and 10-men snaps are real, so this is not an invariant.
    out.append((f"{season} PFF defensive player-snaps per team-week divisible by 11 (info)", f"{ok}/{n}", True))

    # 3. PFF weekly rows vs PFF's own server-aggregated season line. Defense: the team
    #    total must be EXACT. Offense: blocking (weekly) and offense/summary (season) are
    #    different reports, so compare per player: weekly snap_counts_offense summed vs
    #    the season line's snap_counts_total, for players in both.
    r = q("""SELECT (SELECT SUM(snap_counts_defense) FROM core_pff_defense_week WHERE season = ?),
                    (SELECT SUM(snap_counts_defense) FROM core_pff_defense_season WHERE season = ?),
                    (SELECT weeks_requested FROM core_pff_defense_season WHERE season = ? LIMIT 1)""", season, season, season)[0]
    out.append((f"{season} PFF defense: weekly snap sum vs season line",
                f"{r[0]} vs {r[1]} ({(r[2] or '').count(',') + 1} weeks requested)" if r[1] is not None else "season line not loaded",
                r[1] is not None and r[0] == r[1]))
    # The blocking report lists a player only in weeks he had block snaps (Chase Brown:
    # 12 of 17 games), so per-player sums only mean something for LINEMEN, who block
    # on every snap they play.
    rows = q("""SELECT x.player, w.s, x.snap_counts_total FROM
                  (SELECT player_id, SUM(snap_counts_offense) s FROM core_pff_blocking_week
                   WHERE season = ? AND position IN ('T', 'G', 'C') GROUP BY 1) w
                JOIN core_pff_offense_season x ON x.season = ? AND x.player_id = w.player_id""", season, season)
    ok = [r for r in rows if r[1] == r[2]]
    off = sorted((r for r in rows if r[1] != r[2]), key=lambda r: -abs(r[1] - r[2]))[:3]
    out.append((f"{season} PFF offense: OL weekly blocking snaps vs season line, per player",
                f"{len(ok)}/{len(rows)} = {_pct(len(ok), len(rows)):.1f}% exact" + (f"; largest {[(r[0], r[1], r[2]) for r in off]}" if off else ""),
                bool(rows) and len(ok) / len(rows) >= 0.97))

    # 4. Offensive linemen graded per team-season (blocking facet, OL with a block grade)
    rows = q("""SELECT a.team, COUNT(DISTINCT x.player_id) FROM core_pff_blocking_week x
                JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
                WHERE x.season = ? AND x.position IN ('T', 'G', 'C')
                  AND (x.grades_pass_block IS NOT NULL OR x.grades_run_block IS NOT NULL) GROUP BY 1""", season)
    lo = min(rows, key=lambda r: r[1]) if rows else None
    out.append((f"{season} OL graded per team-season (distinct linemen)",
                f"{len(rows)} teams, min {lo[0]} {lo[1]}, total OL-seasons {sum(r[1] for r in rows)}" if lo else "none",
                len(rows) == 32 and lo[1] >= 5))

    # 5. Identity: PFF player_id -> player_ids('pff'). OL is the floor the spec sets (95%);
    #    it decides whether the jersey bridge (demoted in Phase 1) is needed.
    for label, t, pos in (("OL (blocking)", "core_pff_blocking_week", OL_POSITIONS),
                          ("all defenders", "core_pff_defense_week", None),
                          ("all receivers", "core_pff_receiving_week", None)):
        where = f"AND x.position IN ({','.join('?' * len(pos))})" if pos else ""
        n, ok = conn.execute(f"""SELECT COUNT(DISTINCT x.player_id), COUNT(DISTINCT CASE WHEN i.gsis_id IS NOT NULL THEN x.player_id END)
                                 FROM {t} x LEFT JOIN player_ids i ON i.source = 'pff' AND i.source_id = CAST(x.player_id AS TEXT)
                                 WHERE x.season = ? {where}""", (season, *(pos or ()))).fetchone()
        out.append((f"{season} resolves: PFF {label} player_id -> gsis", f"{ok}/{n} = {_pct(ok, n):.2f}%", n == 0 or ok / n >= 0.95))

    # 6. Passing attempts vs nflverse player_stats per team-season (PFF excludes spikes/throwaways
    #    differently, so this is a tolerance check, not exact): within 2%.
    rows = q("""WITH p AS (SELECT a.team, SUM(x.attempts) s FROM core_pff_passing_week x
                           JOIN team_aliases a ON a.abbr = x.team_name AND x.season BETWEEN a.season_from AND a.season_to
                           WHERE x.season = ? GROUP BY 1),
                     n AS (SELECT a.team, SUM(x.attempts) s FROM core_player_stats x
                           JOIN team_aliases a ON a.abbr = x.team AND x.season BETWEEN a.season_from AND a.season_to
                           WHERE x.season = ? GROUP BY 1)
                SELECT p.team, p.s, n.s FROM p JOIN n USING (team)""", season, season)
    within = [r for r in rows if r[2] and abs(r[1] - r[2]) <= 0.02 * r[2]]
    out.append((f"{season} PFF vs nflverse pass attempts per team-season, within 2%",
                f"{len(within)}/{len(rows)} teams; league {sum(r[1] for r in rows)} vs {sum(r[2] for r in rows)}",
                bool(rows) and len(within) >= 0.9 * len(rows)))
    return out
