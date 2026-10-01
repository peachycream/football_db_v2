import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import { Field, Segmented } from '@/components/ui/primitives';
import PlayerLink from '@/components/PlayerLink';
import type { NavOrigin } from '@/lib/playerNav';
import {
  fetchMatchupMeta, fetchRankings, fetchTrends, statLabel,
  OFF_POSITIONS, DEF_POSITIONS, ST_POSITIONS,
  type MatchupMeta, type Position, type RankingsResponse, type Side,
  type TrendsResponse, type ScoringMeta,
} from '@/lib/matchupsApi';
import { token, tokenRgba, catColor } from '@/lib/tokens';

// ---------------------------------------------------------------------------
// In-Season Positional Matchup Tool (MATCHUP_TOOL_BUILD.md Phase 3).
//
// Ranks every team by the fantasy points it ALLOWS to a position group, then
// lists the players whose upcoming opponent ranks worst. Rank 1 = allows the
// most = the best matchup to target.
//
// Filters live in the URL query string, so the page is fully URL-driven and
// PlayerLink's origin-state return needs no sessionStorage snapshot (same
// approach as Ownership -- see lib/playerNav.ts).
//
// The trend chart is hand-rolled inline SVG, following SnapTrend.tsx. Recharts
// is not a dependency and Plotly is lazy-loaded for the Scatter Explorer only;
// adding a chart library for one line chart would regress every page's bundle.
// ---------------------------------------------------------------------------

// One line per team. catColor() excludes the accent on purpose -- a series
// must never read as "this is interactive".
const MAX_TREND_TEAMS = 6;

type TrendMode = 'season' | 'last4';

function readParams() {
  const p = new URLSearchParams(window.location.search);
  const pos = (p.get('position') || 'WR').toUpperCase() as Position;
  return {
    season: Number(p.get('season')) || 0,
    week: p.get('week') ? Number(p.get('week')) : null,
    position: pos,
    scoring: p.get('scoring') || 'ppr',
    teams: (p.get('teams') || '').split(',').filter(Boolean),
  };
}

export default function MatchupTool() {
  const initial = useRef(readParams());

  const [meta, setMeta] = useState<MatchupMeta | null>(null);
  const [bootErr, setBootErr] = useState<string | null>(null);

  const [season, setSeason] = useState<number>(initial.current.season);
  const [week, setWeek] = useState<number | null>(initial.current.week);
  const [position, setPosition] = useState<Position>(initial.current.position);
  const [scoring, setScoring] = useState<string>(initial.current.scoring);
  const [trendTeams, setTrendTeams] = useState<string[]>(initial.current.teams);
  const [trendMode, setTrendMode] = useState<TrendMode>('season');

  const [data, setData] = useState<RankingsResponse | null>(null);
  const [trends, setTrends] = useState<TrendsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showScoringDetail, setShowScoringDetail] = useState(false);

  const side: Side = (OFF_POSITIONS as readonly string[]).includes(position)
    ? 'off'
    : (ST_POSITIONS as readonly string[]).includes(position)
      ? 'st'
      : 'def';

  // bootstrap
  useEffect(() => {
    let cancelled = false;
    fetchMatchupMeta()
      .then((m) => {
        if (cancelled) return;
        setMeta(m);
        setSeason((s) => s || m.seasons[0]);
        // >>> THIS WAS A LITERAL 10 AND IT IS THE WHOLE BUG. <<< The SEASON
        // default was already derived (m.seasons[0] = 2026), so the tool
        // opened on "2026 Week 10" and reported that no players resolved --
        // which reads as a data problem and is not one. Week 10 of 2026 has
        // not been played; the week you want is the one you are about to set
        // a lineup for. `meta.latest.week` is that week, derived server-side
        // and clamped so a closed season cannot ask for a week past its end.
        setWeek((w) => (w == null ? (m.latest?.week ?? null) : w));
      })
      .catch((e) => !cancelled && setBootErr(e instanceof Error ? e.message : String(e)));
    return () => { cancelled = true; };
  }, []);

  // keep the URL in sync so the page is fully URL-driven (PlayerLink origin)
  useEffect(() => {
    if (!season) return;
    const u = new URLSearchParams({ season: String(season), position, scoring });
    if (week != null) u.set('week', String(week));
    if (trendTeams.length) u.set('teams', trendTeams.join(','));
    window.history.replaceState(null, '', `${window.location.pathname}?${u}`);
  }, [season, week, position, scoring, trendTeams]);

  // Sleeper leagues are offense-only. `side` is DERIVED from `position`, so
  // picking an IDP position while a Sleeper league is selected would fire a
  // request the API correctly rejects with a 400. Fall back to generic PPR
  // instead of surfacing an error the user did nothing wrong to cause.
  useEffect(() => {
    if (side === 'off' || !meta) return;   // 'def' and 'st' are both non-offense
    if (meta.scoring_options.find((o) => o.id === scoring)?.off_only) {
      setScoring('ppr');
    }
  }, [side, scoring, meta]);

  const tok = useRef(0);
  useEffect(() => {
    if (!season) return;
    const t = ++tok.current;
    setLoading(true);
    setErr(null);
    Promise.all([
      fetchRankings({ season, week, position, scoring }),
      fetchTrends({ season, position, scoring, teams: trendTeams }),
    ])
      .then(([r, tr]) => {
        if (t !== tok.current) return;
        setData(r);
        setTrends(tr);
      })
      .catch((e) => {
        if (t !== tok.current) return;
        setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => { if (t === tok.current) setLoading(false); });
  }, [season, week, position, scoring, trendTeams]);

  // default the chart to the three worst defenses whenever the user has not
  // picked any teams themselves
  useEffect(() => {
    if (trendTeams.length === 0 && data && data.rankings.length >= 3) {
      setTrendTeams(data.rankings.slice(0, 3).map((r) => r.team));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const toggleTeam = useCallback((team: string) => {
    setTrendTeams((cur) => {
      if (cur.includes(team)) return cur.filter((t) => t !== team);
      if (cur.length >= MAX_TREND_TEAMS) return cur;
      return [...cur, team];
    });
  }, []);

  const origin: NavOrigin = {
    view: `${window.location.pathname}${window.location.search}`,
    label: 'Matchups',
  };

  if (bootErr) {
    return <Centered kind="error" text={`Failed to load matchup metadata: ${bootErr}`} />;
  }
  if (!meta || !season) return <Centered text="Loading…" />;

  const positions =
    side === 'off' ? OFF_POSITIONS : side === 'st' ? ST_POSITIONS : DEF_POSITIONS;

  // Sleeper leagues are OFFENSE-ONLY (they carry no IDP scoring), and the API
  // refuses them for IDP positions. Hide them on the IDP side rather than
  // letting the user pick something that 400s.
  const scoringOptions = meta.scoring_options.filter(
    (o) => side === 'off' || !o.off_only,   // Sleeper hidden off the offense side
  );

  return (
    <div className="min-h-screen bg-bg text-text">
      {/* ── header ─────────────────────────────────────────────────────── */}
      <header className="h-12 border-b border-border px-4 flex items-center gap-3 bg-bg-card sticky top-0 z-20">
        <a href="/" className="text-xs text-text-muted hover:text-text transition-colors">← Home</a>
        <h1 className="text-sm font-semibold">Matchup Tool</h1>
        <span className="hidden md:inline text-[10px] uppercase tracking-wider text-text-dim">
          Fantasy points allowed by position
        </span>
        {loading && <span className="text-text-dim text-xs">updating…</span>}
        <div className="ml-auto flex items-center gap-3 text-xs">
          <a href="/viz/defense" className="text-text-muted hover:text-text transition-colors">Team Defense →</a>
          <a href="/scouting/" className="text-text-muted hover:text-text transition-colors">Scouting →</a>
        </div>
      </header>

      {/* ── filter bar ─────────────────────────────────────────────────── */}
      <div className="border-b border-border bg-bg-card/50 px-4 py-3 flex flex-wrap items-end gap-4">
        <Field label="Side">
          <Segmented<Side>
            value={side}
            items={[
              { value: 'off', label: 'Offense' },
              { value: 'def', label: 'IDP' },
              { value: 'st', label: 'Kicker' },
            ]}
            onChange={(s) =>
              setPosition(s === 'off' ? 'WR' : s === 'st' ? 'PK' : 'LB')
            }
          />
        </Field>

        <Field label="Position">
          <div className="flex flex-wrap gap-1">
            {positions.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPosition(p)}
                className={cn(
                  'px-2.5 py-1 text-xs font-medium rounded-md border transition-colors',
                  p === position
                    ? 'bg-accent/20 text-accent border-accent/40'
                    : 'bg-bg-elevated text-text-muted border-border hover:text-text',
                )}
              >
                {p}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Season">
          <Select value={String(season)} onChange={(v) => setSeason(Number(v))}
                  options={meta.seasons.map((s) => ({ value: String(s), label: String(s) }))} />
        </Field>

        <Field label="Week" hint="rankings use weeks 1…week−1">
          <Select
            value={week == null ? '' : String(week)}
            onChange={(v) => setWeek(v === '' ? null : Number(v))}
            options={[{ value: '', label: 'Full season' },
                      ...meta.weeks.map((w) => ({ value: String(w), label: `Week ${w}` }))]}
          />
        </Field>

        <Field label="Scoring">
          <Select value={scoring} onChange={setScoring}
                  options={scoringOptions.map((o) => ({ value: o.id, label: o.name }))} />
        </Field>

        {data && (
          <div className="ml-auto text-[11px] text-text-dim max-w-md">
            <button
              type="button"
              onClick={() => setShowScoringDetail((v) => !v)}
              className="underline decoration-dotted hover:text-text-muted"
            >
              {showScoringDetail ? 'hide' : 'how these points are scored'}
            </button>
          </div>
        )}
      </div>

      {showScoringDetail && data && <ScoringDetail scoring={data.scoring} />}

      {(err || (data?.warnings.length ?? 0) > 0) && (
        <div className="px-4 py-2 border-b border-border text-xs flex flex-col gap-1">
          {err && <div className="text-error">⨯ {err}</div>}
          {data?.warnings.map((w, i) => <div key={i} className="text-warn">⚠ {w}</div>)}
        </div>
      )}

      {/* ── body ───────────────────────────────────────────────────────── */}
      <div className="p-4 grid grid-cols-1 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] gap-4">
        <RankingsTable
          data={data}
          trendTeams={trendTeams}
          onToggleTeam={toggleTeam}
        />
        <TopPlayers data={data} origin={origin} />
      </div>

      <div className="px-4 pb-8">
        <TrendChart
          trends={trends}
          mode={trendMode}
          onMode={setTrendMode}
          position={position}
          teams={trendTeams}
        />
      </div>
    </div>
  );
}

/* ═════════════════════════════════════════════════════════════════════════
 * Rankings table
 * ═══════════════════════════════════════════════════════════════════════ */

function RankingsTable({
  data, trendTeams, onToggleTeam,
}: {
  data: RankingsResponse | null;
  trendTeams: string[];
  onToggleTeam: (t: string) => void;
}) {
  if (!data) return <Panel title="Teams by points allowed"><Skeleton /></Panel>;
  const cols = data.descriptive_columns;

  return (
    <Panel
      title={`Teams by ${data.position} fantasy points allowed`}
      subtitle={
        data.week_range
          ? `${data.season} · weeks ${data.week_range.from}–${data.week_range.to} · rank 1 allows the most`
          : `${data.season} · rank 1 allows the most`
      }
      right={
        data.scoring.idp_calibration != null ? (
          <span
            className="shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium tabular-nums bg-accent/20 text-accent border-accent/40"
            title={
              `League-scored ${data.position} is multiplied by an empirical calibration of ` +
              `${data.scoring.idp_calibration.toFixed(3)} — the median reported/predicted ratio from ` +
              `fantasy_scores (MFL's own reported totals). It corrects the known catch-all ` +
              `understatement of DL/DB so CROSS-position comparison is valid. Within-position ` +
              `order and the matchup multiplier are ratios in which the factor cancels. ` +
              `Add ?calibrate=0 to the API for raw values.`
            }
          >
            IDP calibrated ×{data.scoring.idp_calibration.toFixed(2)}
          </span>
        ) : undefined
      }
    >
      {data.rankings.length === 0 ? (
        <Empty text="No rankings for this selection." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums">
            <thead>
              <tr className="text-text-dim uppercase text-[10px] tracking-wider border-b border-border">
                <th className="text-left py-2 pr-2 font-medium">#</th>
                <th className="text-left py-2 pr-2 font-medium">Team</th>
                <th className="text-right py-2 pr-3 font-medium">FP/G</th>
                <th className="text-right py-2 pr-3 font-medium">G</th>
                {cols.map((c) => (
                  <th key={c} className="text-right py-2 pr-3 font-medium whitespace-nowrap">
                    {statLabel(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rankings.map((r) => {
                const selected = trendTeams.includes(r.team);
                return (
                  <tr
                    key={r.team}
                    onClick={() => onToggleTeam(r.team)}
                    title="Click to add/remove from the trend chart"
                    className={cn(
                      'border-b border-border/40 cursor-pointer transition-colors',
                      selected ? 'bg-accent/10' : 'hover:bg-bg-hover',
                    )}
                  >
                    <td className="py-1.5 pr-2 text-text-dim">{r.rank}</td>
                    <td className="py-1.5 pr-2">
                      <span className={cn('font-semibold', selected && 'text-accent')}>
                        {r.team}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 text-right font-semibold"
                        style={{ color: rampColor(r.rank, data.rankings.length) }}>
                      {r.fp_allowed_per_game.toFixed(2)}
                    </td>
                    <td className="py-1.5 pr-3 text-right text-text-dim">{r.games}</td>
                    {cols.map((c) => (
                      <td key={c} className="py-1.5 pr-3 text-right text-text-muted">
                        {fmt(r.descriptive_per_game[c])}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/* ═════════════════════════════════════════════════════════════════════════
 * Top-10 players facing the worst defenses
 * ═══════════════════════════════════════════════════════════════════════ */

function TopPlayers({ data, origin }: { data: RankingsResponse | null; origin: NavOrigin }) {
  if (!data) return <Panel title="Best matchups"><Skeleton /></Panel>;

  return (
    <Panel
      title={`Best ${data.position} matchups`}
      subtitle={
        data.week
          ? `Week ${data.week} · ranked by projection (recent form × matchup)`
          : 'Pick a week to see players'
      }
    >
      {data.players.length === 0 ? (
        <Empty text={data.week ? 'No players resolved for this week.' : 'Select a week.'} />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {data.players.map((p, i) => (
            <li
              key={`${p.player_id}-${i}`}
              className="rounded-lg border border-border bg-bg-elevated/40 px-3 py-2"
            >
              <div className="flex items-baseline justify-between gap-2">
                <div className="min-w-0 flex items-baseline gap-1.5">
                  <span className="text-text-dim text-[10px] w-4 shrink-0">{i + 1}</span>
                  <PlayerLink
                    playerId={p.player_id}
                    displayName={p.name}
                    origin={origin}
                    className="text-sm font-semibold truncate"
                  />
                  {p.collision && (
                    <span
                      className="text-warn text-[10px] shrink-0"
                      title="This slug carried rows for more than one team in the recent window — a known same-name (two-human) slug collision. Shown, not merged."
                    >
                      ⚠
                    </span>
                  )}
                </div>
                <span className="text-[10px] text-text-dim shrink-0">
                  {p.team} vs {p.opponent}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px]">
                <span className="text-text-muted">
                  opp rank{' '}
                  <span className="font-semibold" style={{ color: rampColor(p.opponent_rank, 32) }}>
                    #{p.opponent_rank}
                  </span>{' '}
                  · allows {p.opponent_fp_allowed_per_game.toFixed(1)}/g
                </span>
                <span
                  className="font-semibold tabular-nums shrink-0"
                  title="Projected points per game = recent form × opponent matchup multiplier. This is the sort key."
                >
                  {p.projected_fp_per_game.toFixed(1)} proj
                </span>
              </div>
              {/* the projection's arithmetic, made visible: base × multiplier */}
              <div className="mt-0.5 flex items-center justify-between text-[10px] text-text-dim tabular-nums">
                <span>
                  base {p.recent_fp_per_game.toFixed(1)} · last {p.recent_games}
                </span>
                <span
                  className={cn(
                    'font-medium shrink-0',
                    p.matchup_multiplier >= 1.03 && 'text-accent',
                    p.matchup_multiplier <= 0.97 && 'text-warn',
                  )}
                  title={
                    'Opponent matchup multiplier, centered on the league average: ' +
                    '>1 = easier matchup than average, <1 = tougher. Multiplies the base.'
                  }
                >
                  ×{p.matchup_multiplier.toFixed(3)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* ═════════════════════════════════════════════════════════════════════════
 * Trend chart — hand-rolled inline SVG (SnapTrend.tsx pattern)
 * ═══════════════════════════════════════════════════════════════════════ */

const H = 260;
const M = { t: 18, r: 16, b: 26, l: 40 };

function TrendChart({
  trends, mode, onMode, position, teams,
}: {
  trends: TrendsResponse | null;
  mode: TrendMode;
  onMode: (m: TrendMode) => void;
  position: Position;
  teams: string[];
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  const [hoverWeek, setHoverWeek] = useState<number | null>(null);

  // Deps are [hasTeams], NOT []: wrapRef's div only mounts once at least one
  // team is selected, and on a cold load `teams` starts empty and is filled in
  // a moment later from the rankings response. An empty-deps effect would run
  // once against a div that does not exist yet, attach the ResizeObserver to
  // nothing, never retry, leave `w` at 0 -- and the chart would silently never
  // draw. This is the same trap SnapTrend.tsx documents for its [side] deps.
  const hasTeams = teams.length > 0;
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(Math.floor(e.contentRect.width));
    });
    ro.observe(el);
    setW(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, [hasTeams]);

  const series = trends?.series ?? [];

  const layout = useMemo(() => {
    if (!w || series.length === 0) return null;
    const innerW = Math.max(0, w - M.l - M.r);
    const innerH = H - M.t - M.b;

    const pick = (s: (typeof series)[number]) =>
      mode === 'season'
        ? s.weekly.map((p) => ({ week: p.week, v: p.fp_allowed_per_game }))
        : s.last4_rolling.map((p) => ({ week: p.week, v: p.fp_allowed_per_game }));

    const all = series.flatMap(pick);
    const weeks = Array.from(new Set(all.map((p) => p.week))).sort((a, b) => a - b);
    if (weeks.length === 0) return null;
    const minW = weeks[0];
    const maxW = weeks[weeks.length - 1];
    const span = Math.max(1, maxW - minW);
    const vals = all.map((p) => p.v).filter((v): v is number => v != null);
    const maxV = Math.max(1, ...vals);
    const niceMax = Math.ceil(maxV / 5) * 5 || 5;

    const x = (week: number) => M.l + ((week - minW) / span) * innerW;
    const y = (v: number) => M.t + innerH - (v / niceMax) * innerH;

    const lines = series.map((s, i) => {
      const pts = pick(s)
        .filter((p) => p.v != null)
        .map((p) => ({ week: p.week, v: p.v as number, px: x(p.week), py: y(p.v as number) }));
      return { team: s.team, color: catColor(i), pts,
               path: pts.map((n, j) => `${j ? 'L' : 'M'}${n.px.toFixed(1)},${n.py.toFixed(1)}`).join(' ') };
    });

    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const v = Math.round(niceMax * f);
      return { v, py: y(v) };
    });

    return { innerW, innerH, weeks, minW, maxW, niceMax, x, y, lines, yTicks };
  }, [w, series, mode]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!layout) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const scaleX = rect.width ? w / rect.width : 1;
    const mx = (e.clientX - rect.left) * scaleX;
    let best = layout.weeks[0];
    let bestD = Infinity;
    for (const wk of layout.weeks) {
      const d = Math.abs(layout.x(wk) - mx);
      if (d < bestD) { bestD = d; best = wk; }
    }
    setHoverWeek(best);
  };

  return (
    <Panel
      title={`${position} fantasy points allowed by week`}
      subtitle={
        mode === 'season'
          ? 'Each week in isolation'
          : 'Last-4 rolling — SUM(points)/SUM(games) over the window, not an average of weekly rates'
      }
      right={
        <Segmented<TrendMode>
          value={mode}
          items={[{ value: 'season', label: 'Full season' }, { value: 'last4', label: 'Last 4' }]}
          onChange={onMode}
        />
      }
    >
      {teams.length === 0 ? (
        <Empty text="Click a team in the table to chart it." />
      ) : (
        <>
          <div className="flex flex-wrap gap-3 mb-2">
            {(layout?.lines ?? []).map((l) => {
              const s = series.find((x) => x.team === l.team);
              return (
                <span key={l.team} className="inline-flex items-center gap-1.5 text-[11px]">
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ background: l.color }} />
                  <span className="text-text font-medium">{l.team}</span>
                  <span className="text-text-dim tabular-nums">
                    {s?.season_fp_allowed_per_game?.toFixed(2) ?? '—'}/g
                  </span>
                </span>
              );
            })}
          </div>

          <div ref={wrapRef} className="relative w-full">
            {layout ? (
              <>
                <svg width={w} height={H} onMouseMove={onMove}
                     onMouseLeave={() => setHoverWeek(null)} className="block">
                  {layout.yTicks.map((t) => (
                    <g key={t.v}>
                      <line x1={M.l} x2={w - M.r} y1={t.py} y2={t.py}
                            stroke="rgb(255 255 255 / 0.06)" strokeDasharray="3 3" />
                      <text x={M.l - 6} y={t.py + 3} textAnchor="end" fontSize={10} fill={token('tx-mut')}>
                        {t.v}
                      </text>
                    </g>
                  ))}
                  {layout.weeks.map((wk) => (
                    <text key={wk} x={layout.x(wk)} y={H - 8} textAnchor="middle"
                          fontSize={10} fill={token('tx-mut')}>
                      {wk}
                    </text>
                  ))}
                  {hoverWeek != null && (
                    <line x1={layout.x(hoverWeek)} x2={layout.x(hoverWeek)}
                          y1={M.t} y2={H - M.b} stroke="rgb(255 255 255 / 0.15)" />
                  )}
                  {layout.lines.map((l) => (
                    <g key={l.team}>
                      <path d={l.path} fill="none" stroke={l.color} strokeWidth={2} />
                      {l.pts.map((n) => (
                        <circle key={`${l.team}-${n.week}`} cx={n.px} cy={n.py}
                                r={hoverWeek === n.week ? 4 : 2.5}
                                fill={l.color} stroke={token('bg')} strokeWidth={1} />
                      ))}
                    </g>
                  ))}
                </svg>

                {hoverWeek != null && (
                  <div
                    className="pointer-events-none absolute z-10 rounded-md border border-border
                               bg-bg-card px-2.5 py-1.5 text-xs shadow-xl shadow-black/50"
                    style={{
                      left: Math.min(Math.max(layout.x(hoverWeek) - 50, 0), Math.max(0, w - 150)),
                      top: 4,
                    }}
                  >
                    <div className="text-text font-semibold mb-0.5">Week {hoverWeek}</div>
                    {layout.lines.map((l) => {
                      const n = l.pts.find((p) => p.week === hoverWeek);
                      return (
                        <div key={l.team} className="flex items-center gap-1.5 tabular-nums">
                          <span className="w-2 h-2 rounded-sm" style={{ background: l.color }} />
                          <span className="text-text-muted">{l.team}</span>
                          <span className="text-text">{n ? n.v.toFixed(2) : '—'}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            ) : (
              <div style={{ height: H }} />
            )}
          </div>
        </>
      )}
    </Panel>
  );
}

/* ═════════════════════════════════════════════════════════════════════════
 * Scoring transparency panel
 * ═══════════════════════════════════════════════════════════════════════ */

function ScoringDetail({ scoring }: { scoring: ScoringMeta }) {
  return (
    <div className="px-4 py-3 border-b border-border bg-bg-elevated/30 text-[11px] flex flex-col gap-2">
      <div className="text-text-muted">
        <span className="font-semibold text-text">
          {scoring.mode === 'league' ? scoring.league_name : 'Generic PPR'}
        </span>
        {scoring.rule_source && (
          <span className="text-text-dim"> · rules from {scoring.rule_source}</span>
        )}
      </div>
      {scoring.mapping_notes.map((n, i) => (
        <div key={i} className="text-text-dim">· {n}</div>
      ))}
      <div>
        <span className="text-text-muted">Scored: </span>
        <span className="text-text-dim">
          {scoring.scored_components.map(statLabel).join(', ') || 'nothing'}
        </span>
      </div>
      {scoring.unscored_components.length > 0 && (
        <details>
          <summary className="cursor-pointer text-warn">
            {scoring.unscored_components.length} component(s) not scored — why
          </summary>
          <ul className="mt-1 flex flex-col gap-0.5 pl-3">
            {scoring.unscored_components.map((u) => (
              <li key={u.component} className="text-text-dim">
                <span className="text-text-muted">{statLabel(u.component)}</span> — {u.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/* ═════════════════════════════════════════════════════════════════════════
 * Small presentational helpers
 * ═══════════════════════════════════════════════════════════════════════ */

function Panel({
  title, subtitle, right, children,
}: {
  title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-bg-card p-4 min-w-0">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h2 className="text-xs uppercase tracking-wider text-text-muted">{title}</h2>
          {subtitle && <p className="text-[11px] text-text-dim mt-0.5">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

function Select({
  value, onChange, options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-7 rounded-md bg-bg-elevated border border-border px-2 text-xs text-text
                 focus:outline-none focus:ring-1 focus:ring-accent/40"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function Centered({ text, kind = 'info' }: { text: string; kind?: 'info' | 'error' }) {
  return (
    <div className="h-screen w-screen flex items-center justify-center bg-bg">
      <div className={kind === 'error' ? 'text-error text-sm' : 'text-text-muted text-sm'}>{text}</div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="h-32 flex items-center justify-center border border-dashed border-border rounded-lg">
      <p className="text-text-dim text-xs">{text}</p>
    </div>
  );
}

function Skeleton() {
  return <div className="h-48 rounded-lg bg-bg-elevated/40 animate-pulse" />;
}

/**
 * Rank 1 (allows the most — the best matchup) → last (allows the least).
 * On the app's diverging scale: amber↔cyan rather than red↔green, because
 * these panels get screenshotted and red/green is the worst pairing for
 * deuteranopia. The rank number is always shown alongside, so hue is
 * reinforcement rather than the only channel.
 */
function rampColor(rank: number, n: number): string {
  if (n <= 1) return token('tx-mut');
  const f = (rank - 1) / (n - 1);
  if (f < 0.2) return token('div-neg');
  if (f < 0.4) return token('mid');
  if (f < 0.6) return token('tx-mut');
  if (f < 0.8) return tokenRgba('div-pos', 0.65);
  return token('div-pos');
}

function fmt(v: number | undefined): string {
  if (v == null) return '—';
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
