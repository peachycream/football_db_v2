import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { Field, Popover, Button, Segmented } from '@/components/ui/primitives';
import {
  fetchTeamDefenseEnv,
  DEFENV_TEAMS,
  DEFENV_SEASONS,
  type TeamDefenseEnvResponse,
  type MetricObj,
} from '@/lib/defenvApi';
import { token } from '@/lib/tokens';
import { defaultSeason } from '@/lib/seasonCtx';
import { ChatToggleButton } from '@/components/chat/ChatToggleButton';
import { DefenvChatDrawer } from '@/components/chat/DefenvChatDrawer';

// Same percentile color ramp as TeamOffenseDashboard.tsx -- pct always means
// "higher = better" regardless of metric (already inverted server-side where
// needed, e.g. lower EPA/play allowed -> higher pct).
// Percentile bands on the app's diverging scale (amber↔cyan, not red↔green:
// see theme.css). Read once at module load, which is safe because theme.css
// is a blocking <head> link and the bundle's module script is deferred.
// None of these is the accent, so a per-tool accent does not affect them.
const PCT_RED = token('div-neg');
const PCT_AMBER = token('mid');
const PCT_NEUTRAL = token('tx-mut');
const PCT_GREEN = token('div-pos');

function pctColor(pct: number | null): string {
  if (pct == null) return PCT_NEUTRAL;
  if (pct < 25) return PCT_RED;
  if (pct < 50) return PCT_AMBER;
  if (pct < 75) return PCT_NEUTRAL;
  return PCT_GREEN;
}

function fmtPct(v: number | null, digits = 1): string {
  if (v == null) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}
function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return '—';
  return v.toFixed(digits);
}

type WeekMode = 'single' | 'range' | 'all';

// ---------------------------------------------------------------------------
// Small self-contained select (duplicated from TeamOffenseDashboard.tsx --
// that component isn't exported).
// ---------------------------------------------------------------------------
interface Opt { value: string; label: string }
function TeamSelectMenu({ value, options, onChange }: { value: string; options: Opt[]; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value);
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      align="left"
      trigger={
        <Button variant="outline" size="sm" className="w-full justify-between">
          <span className="truncate">{current?.label ?? 'Select'}</span>
          <span className="text-text-dim ml-1">▾</span>
        </Button>
      }
    >
      <div className="max-h-72 overflow-auto py-1">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => { onChange(o.value); setOpen(false); }}
            className={cn(
              'w-full text-left px-3 py-1.5 text-sm transition-colors',
              o.value === value ? 'text-accent' : 'text-text-muted hover:text-text hover:bg-bg-elevated',
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </Popover>
  );
}

// ---------------------------------------------------------------------------
// Chip: value + percentile bar (or n= badge when pct is null)
// ---------------------------------------------------------------------------
function MetricChip({
  label, obj, fmt = fmtNum, size = 'md',
}: {
  label: string;
  obj: MetricObj | undefined;
  fmt?: (v: number | null) => string;
  size?: 'sm' | 'md' | 'lg';
}) {
  const color = pctColor(obj?.pct ?? null);
  const valueClass = size === 'lg' ? 'text-2xl' : size === 'sm' ? 'text-sm' : 'text-lg';
  return (
    <div className="rounded-md border border-border bg-bg-card px-3 py-2">
      <div className="flex items-baseline justify-between gap-1">
        <div className="text-[9px] uppercase tracking-wider text-text-dim truncate">{label}</div>
        {obj?.rank != null && obj?.n_teams != null && (
          <div className="text-[9px] text-text-dim tabular-nums shrink-0">#{obj.rank}/{obj.n_teams}</div>
        )}
      </div>
      <div className={cn('font-semibold tabular-nums', valueClass)} style={{ color }}>
        {fmt(obj?.v ?? null)}
      </div>
      {obj?.pct != null ? (
        <div className="mt-1 h-1 rounded-full bg-bg-elevated overflow-hidden">
          <div className="h-full rounded-full" style={{ width: `${obj.pct}%`, backgroundColor: color }} />
        </div>
      ) : (
        <div className="mt-1 text-[9px] text-text-dim">n={obj?.n ?? 0}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sparkline: dependency-free inline SVG (same as TeamOffenseDashboard.tsx)
// ---------------------------------------------------------------------------
function Sparkline({
  data, medianData, color = PCT_GREEN, width = 100, height = 28,
}: {
  data: [number, number | null][];
  medianData?: [number, number | null][];
  color?: string;
  width?: number;
  height?: number;
}) {
  const vals = data.map((d) => d[1]).filter((v): v is number => v != null);
  const medianVals = (medianData ?? []).map((d) => d[1]).filter((v): v is number => v != null);
  const allVals = [...vals, ...medianVals];
  if (vals.length < 2) {
    return <div style={{ height }} className="flex items-center text-[9px] text-text-dim">n/a</div>;
  }
  const min = Math.min(...allVals);
  const max = Math.max(...allVals);
  const range = max - min || 1;
  const toPoints = (series: [number, number | null][]) =>
    series
      .map((d, i) => {
        if (d[1] == null) return null;
        const x = (i / (series.length - 1 || 1)) * width;
        const y = height - ((d[1] - min) / range) * height;
        return `${x},${y}`;
      })
      .filter(Boolean)
      .join(' ');
  return (
    <svg width={width} height={height} className="overflow-visible">
      {medianData && (
        <polyline points={toPoints(medianData)} fill="none" stroke={PCT_NEUTRAL} strokeWidth={1} strokeDasharray="2,2" opacity={0.6} />
      )}
      <polyline points={toPoints(data)} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Auto-blurb: template-based, no LLM call. rankWord's polarity is already
// "higher pct = better" (server-side inversion), so this reads identically
// to the offense side's own blurb logic despite describing the opposite
// side of the ball.
// ---------------------------------------------------------------------------
function rankWord(pct: number | null): string {
  if (pct == null) return 'unranked';
  if (pct >= 90) return 'top-5';
  if (pct >= 75) return 'top-10';
  if (pct >= 50) return 'top-16';
  if (pct >= 25) return 'bottom-16';
  return 'bottom-10';
}
function buildBlurb(epaObj: MetricObj, havocObj: MetricObj): string {
  const efficiency = `${rankWord(epaObj.pct)} defense by EPA/play allowed`;
  const havoc = `${rankWord(havocObj.pct)} havoc rate`;
  return `${efficiency}, ${havoc}.`;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
// Derived from team_def_env_weekly -- see lib/seasonCtx.ts.
const DEFAULT_SEASON = defaultSeason('defense');

export default function TeamDefenseDashboard() {
  const [season, setSeason] = useState<number>(DEFAULT_SEASON);
  const [team, setTeam] = useState<string>('BUF');
  const [weekMode, setWeekMode] = useState<WeekMode>('all');
  const [singleWeek, setSingleWeek] = useState(1);
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(18);

  const [data, setData] = useState<TeamDefenseEnvResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const [weekStart, weekEnd] = useMemo<[number, number]>(() => {
    if (weekMode === 'single') return [singleWeek, singleWeek];
    if (weekMode === 'range') return [rangeStart, rangeEnd];
    return [1, 18];
  }, [weekMode, singleWeek, rangeStart, rangeEnd]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTeamDefenseEnv({ season, team, weekStart, weekEnd })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(String(e.message || e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [season, team, weekStart, weekEnd]);

  return (
    <div className="min-h-screen bg-bg text-text font-sans">
      {/* Filter bar (sticky) -------------------------------------------------- */}
      <div className="sticky top-0 z-20 border-b border-border bg-bg/95 backdrop-blur px-4 py-3">
        <div className="flex items-center gap-2 flex-wrap max-w-[1700px] mx-auto">
          <a href="/" className="text-xs text-text-dim hover:text-accent mr-2">← Hub</a>
          <span className="text-sm font-semibold text-accent mr-4">TEAM DEFENSE</span>

          <Field label="Season" className="w-24">
            <TeamSelectMenu
              value={String(season)}
              options={DEFENV_SEASONS.map((s) => ({ value: String(s), label: String(s) }))}
              onChange={(v) => setSeason(Number(v))}
            />
          </Field>

          <Field label="Team" className="w-28">
            <TeamSelectMenu
              value={team}
              options={DEFENV_TEAMS.map((t) => ({ value: t, label: t }))}
              onChange={setTeam}
            />
          </Field>

          <Field label="Weeks" className="w-auto">
            <Segmented
              value={weekMode}
              items={[
                { value: 'single', label: 'Single' },
                { value: 'range', label: 'Range' },
                { value: 'all', label: 'All' },
              ]}
              onChange={setWeekMode}
            />
          </Field>

          {weekMode === 'single' && (
            <input
              type="number" min={1} max={22} value={singleWeek}
              onChange={(e) => setSingleWeek(Number(e.target.value))}
              className="w-16 rounded-md border border-border bg-bg-card px-2 py-1 text-sm"
            />
          )}
          {weekMode === 'range' && (
            <div className="flex items-center gap-1">
              <input
                type="number" min={1} max={22} value={rangeStart}
                onChange={(e) => setRangeStart(Number(e.target.value))}
                className="w-14 rounded-md border border-border bg-bg-card px-2 py-1 text-sm"
              />
              <span className="text-text-dim">–</span>
              <input
                type="number" min={1} max={22} value={rangeEnd}
                onChange={(e) => setRangeEnd(Number(e.target.value))}
                className="w-14 rounded-md border border-border bg-bg-card px-2 py-1 text-sm"
              />
            </div>
          )}

          <div className="ml-auto flex items-center gap-4">
            <a
              href="/glossary/#def-epa-play"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-text-dim hover:text-accent"
            >
              📖 Glossary
            </a>
            <ChatToggleButton open={chatOpen} onClick={() => setChatOpen((v) => !v)} />
          </div>
        </div>
      </div>

      <div className="p-4 max-w-[1700px] mx-auto space-y-4">
        {loading && <div className="text-text-dim text-sm">Loading…</div>}
        {error && <div className="text-error text-sm">{error}</div>}

        {data && (
          <>
            {/* Identity header -- spans the full width, above both columns -- */}
            <div className="rounded-lg border border-border bg-bg-card p-4">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                  <div className="text-2xl font-bold">{data.team}</div>
                  <div className="text-sm text-text-muted">
                    {data.season} · weeks {data.weeks[0]}–{data.weeks[1]} · record {data.header.record_allowed ?? '—'}
                  </div>
                  {data.header.game && (
                    <div className="mt-1 flex items-center gap-2 text-sm">
                      <span
                        className="font-bold"
                        style={{
                          color: data.header.game.result === 'W' ? PCT_GREEN
                            : data.header.game.result === 'L' ? PCT_RED : PCT_NEUTRAL,
                        }}
                      >
                        {data.header.game.result ?? '—'}
                      </span>
                      <span className="text-text">
                        {data.header.game.team_score ?? '—'}–{data.header.game.opp_score ?? '—'}
                      </span>
                      <span className="text-text-dim">
                        {data.header.game.home_away === 'home' ? 'vs' : '@'} {data.header.game.opponent}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <MetricChip label="EPA/play allowed" obj={data.header.epa_play_allowed} size="lg" />
                  <MetricChip label="Havoc rate" obj={data.header.havoc_rate} fmt={(v) => fmtPct(v)} size="lg" />
                  <MetricChip label="Plays faced/game" obj={data.header.plays_faced_per_game} fmt={(v) => fmtNum(v, 1)} size="lg" />
                </div>
              </div>
              <div className="mt-3 text-sm text-text-muted italic">
                {buildBlurb(data.header.epa_play_allowed, data.header.havoc_rate)}
              </div>
            </div>

            {/* Two-column body: main stack left, League Context sticky alongside. */}
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_460px] gap-4 items-start">
              <div className="space-y-4 min-w-0">
                {/* Volume / Efficiency ------------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">Volume &amp; Efficiency Allowed</div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <MetricChip label="EPA/play allowed" obj={data.volume_efficiency.epa_per_play_allowed} size="sm" />
                    <MetricChip label="Success rate allowed" obj={data.volume_efficiency.success_rate_allowed} fmt={fmtPct} size="sm" />
                    <MetricChip label="Explosive rate allowed" obj={data.volume_efficiency.explosive_rate_allowed} fmt={fmtPct} size="sm" />
                    <MetricChip label="Pass EPA/play allowed" obj={data.volume_efficiency.pass_epa_per_play_allowed} size="sm" />
                    <MetricChip label="Rush EPA/play allowed" obj={data.volume_efficiency.rush_epa_per_play_allowed} size="sm" />
                    <MetricChip label="Early-down EPA/play" obj={data.volume_efficiency.early_epa_per_play} size="sm" />
                    <MetricChip label="Late-down EPA/play" obj={data.volume_efficiency.late_epa_per_play} size="sm" />
                    <MetricChip label="PROE faced" obj={data.volume_efficiency.proe_faced} fmt={fmtPct} size="sm" />
                    <MetricChip label="Neutral sec/snap faced" obj={data.volume_efficiency.neutral_sec_per_snap_faced} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Points/drive allowed" obj={data.volume_efficiency.pts_per_drive_allowed} fmt={(v) => fmtNum(v, 2)} size="sm" />
                  </div>
                </div>

                {/* Pass Rush -------------------------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">Pass Rush</div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <MetricChip label="Pressure rate" obj={data.pass_rush.pressure_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="Sack rate allowed" obj={data.pass_rush.sack_rate_allowed} fmt={fmtPct} size="sm" />
                    <MetricChip label="Hurry rate" obj={data.pass_rush.hurry_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="QB hit rate" obj={data.pass_rush.qb_hit_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="4-man pressure rate (FTN)" obj={data.pass_rush.pressure_rate_4man_ftn} fmt={fmtPct} size="sm" />
                  </div>
                </div>

                {/* Coverage --------------------------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">Coverage</div>
                  <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                    <MetricChip label="Comp % allowed" obj={data.coverage.comp_pct_allowed} fmt={fmtPct} size="sm" />
                    <MetricChip label="Yards/att allowed" obj={data.coverage.yards_per_att_allowed} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Passer rating allowed" obj={data.coverage.passer_rating_allowed} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="CPOE allowed" obj={data.coverage.cpoe_allowed} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Yards/coverage snap" obj={data.coverage.yards_per_coverage_snap_allowed} fmt={(v) => fmtNum(v, 2)} size="sm" />
                    <MetricChip label="Deep target rate allowed" obj={data.coverage.deep_target_rate_allowed} fmt={fmtPct} size="sm" />
                  </div>
                </div>

                {/* Run Defense + Situational + Havoc -------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">Run Defense / Situational / Havoc</div>
                  <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                    <MetricChip label="YPC allowed" obj={data.run_defense.rush_ypc_allowed} fmt={(v) => fmtNum(v, 2)} size="sm" />
                    <MetricChip label="YCO/att allowed" obj={data.run_defense.yco_per_att_allowed} fmt={(v) => fmtNum(v, 2)} size="sm" />
                    <MetricChip label="Stuff rate" obj={data.run_defense.stuff_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="3rd down conv allowed" obj={data.situational.third_down_rate_allowed} fmt={fmtPct} size="sm" />
                    <MetricChip label="RZ TD% allowed" obj={data.situational.rz_td_rate_allowed} fmt={fmtPct} size="sm" />
                    <MetricChip label="Three-and-out rate forced" obj={data.situational.three_and_out_rate_forced} fmt={fmtPct} size="sm" />
                    <MetricChip label="Havoc rate" obj={data.havoc.havoc_rate} fmt={fmtPct} size="sm" />
                  </div>
                </div>

                {/* Grades ------------------------------------------------------------ */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">PFF Grades</div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <MetricChip label="Defense grade" obj={data.grades.def_grade} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Pass rush grade" obj={data.grades.pass_rush_grade} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Coverage grade" obj={data.grades.coverage_grade} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Run defense grade" obj={data.grades.run_def_grade} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Tackle grade" obj={data.grades.tackle_grade} fmt={(v) => fmtNum(v, 1)} size="sm" />
                  </div>
                </div>

                {/* Scheme (retrospective-only) --------------------------------------- */}
                <SchemePanel scheme={data.scheme} season={data.season} />

                {/* Trend footer -------------------------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">
                    Trend (dashed = league median)
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <TrendCard label="EPA/play allowed" series={data.trend.epa_per_play_allowed} median={data.trend_league_median.epa_per_play_allowed} />
                    <TrendCard label="Success rate allowed" series={data.trend.success_rate_allowed} median={data.trend_league_median.success_rate_allowed} />
                    <TrendCard label="Havoc rate" series={data.trend.havoc_rate} median={data.trend_league_median.havoc_rate} />
                    <TrendCard label="Points/drive allowed" series={data.trend.pts_per_drive_allowed} median={data.trend_league_median.pts_per_drive_allowed} />
                  </div>
                </div>
              </div>

              {/* Right column: League Context, sticky while scrolling the left stack. */}
              <div className="lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-88px)] lg:overflow-y-auto space-y-4">
                <LeagueTable rows={data.league_table} selectedTeam={data.team} />
              </div>
            </div>
          </>
        )}
      </div>

      <DefenvChatDrawer open={chatOpen} onClose={() => setChatOpen(false)} dashboardData={data} />
    </div>
  );
}

function TrendCard({
  label, series, median,
}: {
  label: string;
  series: [number, number | null][];
  median: [number, number | null][];
}) {
  return (
    <div className="rounded-md border border-border-subtle p-2">
      <div className="text-[10px] text-text-dim mb-1">{label}</div>
      <Sparkline data={series} medianData={median} width={140} height={40} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scheme panel -- retrospective-only (participation is post-season-only).
// Labeled "through <season>" per DEF_ENV_BUILD.md's cadence rule; entirely
// absent (not just empty) when the requested season is still in progress.
// ---------------------------------------------------------------------------
const COVER_LABELS: Record<string, string> = {
  cover0_rate: 'Cover 0', cover1_rate: 'Cover 1', cover2_rate: 'Cover 2',
  cover3_rate: 'Cover 3', cover4_rate: 'Cover 4', cover6_rate: 'Cover 6',
  // 2-Man/blown coverage/combo/Cover 9/prevent, see team_def_env.py's own
  // OTHER_COVER_LABELS note -- shown so the 6 named rates don't look like
  // they should (but don't) sum to 100% on their own.
  other_rate: 'Other',
};

function SchemePanel({ scheme, season }: { scheme: TeamDefenseEnvResponse['scheme']; season: number }) {
  if (!scheme) {
    return (
      <div className="rounded-lg border border-border bg-bg-card p-4">
        <div className="text-xs uppercase tracking-wider text-text-dim mb-2">Scheme (Man/Zone/Personnel)</div>
        <div className="text-sm text-text-dim">
          No scheme data for {season} -- participation data only delivers after a season's
          postseason completes, so this section is unavailable for in-progress seasons.
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase tracking-wider text-text-dim">Scheme (Man/Zone/Personnel)</div>
        <div className="text-[10px] text-warn">through {scheme.through_season} (retrospective only)</div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {scheme.man_zone && (
          <>
            <MiniStat label="Man rate" value={fmtPct(scheme.man_zone.man_rate)} />
            <MiniStat label="Zone rate" value={fmtPct(scheme.man_zone.zone_rate)} />
            <MiniStat label="EPA/play vs man" value={fmtNum(scheme.man_zone.epa_per_play_vs_man)} />
            <MiniStat label="EPA/play vs zone" value={fmtNum(scheme.man_zone.epa_per_play_vs_zone)} />
          </>
        )}
        {scheme.blitz_rate != null && <MiniStat label="Blitz rate" value={fmtPct(scheme.blitz_rate)} />}
        {scheme.box_counts && (
          <>
            <MiniStat label="Light-box YPC" value={fmtNum(scheme.box_counts.lightbox_ypc)} />
            <MiniStat label="Heavy-box YPC" value={fmtNum(scheme.box_counts.heavybox_ypc)} />
          </>
        )}
      </div>

      {scheme.coverage_shell && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wider text-text-dim mb-2">Coverage Shell</div>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
            {Object.entries(scheme.coverage_shell).map(([key, v]) => (
              <MiniStat key={key} label={COVER_LABELS[key] ?? key} value={fmtPct(v)} />
            ))}
          </div>
        </div>
      )}

      {scheme.personnel && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wider text-text-dim mb-2">Personnel</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <MiniStat label="Base" value={fmtPct(scheme.personnel.base_rate)} />
            <MiniStat label="Nickel" value={fmtPct(scheme.personnel.nickel_rate)} />
            <MiniStat label="Dime" value={fmtPct(scheme.personnel.dime_rate)} />
            <MiniStat label="Other" value={fmtPct(scheme.personnel.other_rate)} />
          </div>
        </div>
      )}

      {scheme.pff_coverage && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wider text-text-dim mb-2">PFF Coverage Quality (separately labeled -- not blended with participation)</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <MiniStat label="Man catch rate" value={fmtPct(scheme.pff_coverage.man_catch_rate)} />
            <MiniStat label="Man yds/target" value={fmtNum(scheme.pff_coverage.man_yards_per_target)} />
            <MiniStat label="Zone catch rate" value={fmtPct(scheme.pff_coverage.zone_catch_rate)} />
            <MiniStat label="Zone yds/target" value={fmtNum(scheme.pff_coverage.zone_yards_per_target)} />
          </div>
        </div>
      )}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border-subtle p-2">
      <div className="text-[9px] text-text-dim">{label}</div>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function LeagueTable({ rows, selectedTeam }: { rows: TeamDefenseEnvResponse['league_table']; selectedTeam: string }) {
  const [sortKey, setSortKey] = useState<'epa_play_allowed' | 'success_rate_allowed' | 'havoc_rate' | 'pts_per_drive_allowed'>('epa_play_allowed');
  const sorted = useMemo(
    () => [...rows].sort((a, b) => (a[sortKey] ?? Infinity) - (b[sortKey] ?? Infinity)),
    [rows, sortKey],
  );
  const cols: { key: typeof sortKey; label: string; fmt: (v: number | null) => string }[] = [
    { key: 'epa_play_allowed', label: 'EPA/play allowed', fmt: (v) => fmtNum(v, 3) },
    { key: 'success_rate_allowed', label: 'Success % allowed', fmt: fmtPct },
    { key: 'havoc_rate', label: 'Havoc %', fmt: fmtPct },
    { key: 'pts_per_drive_allowed', label: 'Pts/drive allowed', fmt: (v) => fmtNum(v, 2) },
  ];
  return (
    <div className="rounded-lg border border-border bg-bg-card p-4">
      <div className="text-xs uppercase tracking-wider text-text-dim mb-3">League Context (32 teams)</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-text-dim text-xs">
              <th className="text-left py-1 pr-3">#</th>
              <th className="text-left py-1 pr-3">Team</th>
              {cols.map((c) => (
                <th
                  key={c.key}
                  className="text-right py-1 pr-3 cursor-pointer hover:text-accent"
                  onClick={() => setSortKey(c.key)}
                >
                  {c.label}{sortKey === c.key ? ' ▾' : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr
                key={r.team}
                className={cn(
                  'border-t border-border-subtle',
                  r.team === selectedTeam && 'bg-accent/10 font-semibold text-accent',
                )}
              >
                <td className="py-1 pr-3 text-text-dim">{i + 1}</td>
                <td className="py-1 pr-3">{r.team}</td>
                {cols.map((c) => (
                  <td key={c.key} className="py-1 pr-3 text-right tabular-nums">{c.fmt(r[c.key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
