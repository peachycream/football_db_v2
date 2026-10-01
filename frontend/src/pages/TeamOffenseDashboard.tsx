import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { Field, Popover, Button, Segmented, Toggle } from '@/components/ui/primitives';
import {
  fetchTeamOffenseEnv,
  OFFENV_TEAMS,
  OFFENV_SEASONS,
  type TeamOffenseEnvResponse,
  type MetricObj,
  type CoreSplit,
  type PersonnelRow,
  type TargetRateByPosition as TargetRateByPositionData,
} from '@/lib/offenvApi';
import { token, catColor, posColor } from '@/lib/tokens';
import { ChatToggleButton } from '@/components/chat/ChatToggleButton';
import { OffenvChatDrawer } from '@/components/chat/OffenvChatDrawer';
import { defaultSeason } from '@/lib/seasonCtx';

// Percentile color ramp per OFFENSIVE_ENV_BUILD.md section 6 (discrete bands,
// matching the app's existing token palette: error/warn/text.dim/accent).
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
// pff_passing_advanced.pressure_rate is NOT a clean 0-1 fraction like the
// team_env_weekly-derived rates (empirical range 0-50, avg ~5.5 -- far below
// the 20-40% a real "pressure rate" should read) -- displaying it through
// fmtPct's x100 conversion produced nonsense values like 652%. Rendered as
// the raw external value with a '%' suffix, no rescaling, until the ingest's
// true column semantics are confirmed (see OFFENV_AGENT_LOG.md).
function fmtRawPct(v: number | null): string {
  if (v == null) return '—';
  return `${v.toFixed(1)}%`;
}

type WeekMode = 'single' | 'range' | 'all';

// ---------------------------------------------------------------------------
// Small self-contained select (mirrors PlayerDashboard's SelectMenu pattern,
// duplicated locally since that component isn't exported).
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
// Sparkline: dependency-free inline SVG (recharts is not installed)
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
// Auto-blurb: template-based, no LLM call
// ---------------------------------------------------------------------------
function rankWord(pct: number | null): string {
  if (pct == null) return 'unranked';
  if (pct >= 90) return 'top-5';
  if (pct >= 75) return 'top-10';
  if (pct >= 50) return 'top-16';
  if (pct >= 25) return 'bottom-16';
  return 'bottom-10';
}
// Takes the ACTIVE (toggle-aware) epa/proe objects so the blurb narrates
// whichever lens (all vs neutral) the master toggle currently shows -- pace
// is always the neutral-split metric regardless of the toggle (spec's own
// sec_per_snap formula is neutral-split-only, there's no "all-script pace").
function buildBlurb(epaObj: MetricObj, proeObj: MetricObj, paceObj: MetricObj): string {
  const efficiency = `${rankWord(epaObj.pct)} efficiency`;
  const style = proeObj.v != null
    ? (proeObj.v > 0.02 ? 'pass-heavy over expectation' : proeObj.v < -0.02 ? 'run-heavy over expectation' : 'roughly balanced to expectation')
    : 'style undetermined';
  const tempo = `${rankWord(paceObj.pct)} tempo`;
  return `${efficiency}, ${style}, ${tempo}.`;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
// Derived from team_env_weekly. This one legitimately stays on 2025
// while the others move to 2026: its table has no 2026 rows yet, and
// opening on a season with nothing in it is the failure, not the fix.
const DEFAULT_SEASON = defaultSeason('offense');

export default function TeamOffenseDashboard() {
  const [season, setSeason] = useState<number>(DEFAULT_SEASON);
  const [team, setTeam] = useState<string>('BUF');
  const [weekMode, setWeekMode] = useState<WeekMode>('all');
  const [singleWeek, setSingleWeek] = useState(1);
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(18);
  const [neutralOnly, setNeutralOnly] = useState(false);

  const [data, setData] = useState<TeamOffenseEnvResponse | null>(null);
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
    fetchTeamOffenseEnv({ season, team, weekStart, weekEnd })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(String(e.message || e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [season, team, weekStart, weekEnd]);

  // "neutral master toggle" -- re-renders every panel on the neutral lens by
  // swapping which split key every section reads from.
  const activeAll: CoreSplit = neutralOnly ? 'neutral' : 'all';
  const activePass: CoreSplit = neutralOnly ? 'neutral_pass' : 'pass';
  const activeRush: CoreSplit = neutralOnly ? 'neutral_rush' : 'rush';

  return (
    <div className="min-h-screen bg-bg text-text font-sans">
      {/* Filter bar (sticky) -------------------------------------------------- */}
      <div className="sticky top-0 z-20 border-b border-border bg-bg/95 backdrop-blur px-4 py-3">
        <div className="flex items-center gap-2 flex-wrap max-w-[1700px] mx-auto">
          <a href="/" className="text-xs text-text-dim hover:text-accent mr-2">← Hub</a>
          <span className="text-sm font-semibold text-accent mr-4">TEAM OFFENSE</span>

          <Field label="Season" className="w-24">
            <TeamSelectMenu
              value={String(season)}
              options={OFFENV_SEASONS.map((s) => ({ value: String(s), label: String(s) }))}
              onChange={(v) => setSeason(Number(v))}
            />
          </Field>

          <Field label="Team" className="w-28">
            <TeamSelectMenu
              value={team}
              options={OFFENV_TEAMS.map((t) => ({ value: t, label: t }))}
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
              href="/glossary/#off-epa-play"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-text-dim hover:text-accent"
            >
              📖 Glossary
            </a>
            <Toggle checked={neutralOnly} onChange={setNeutralOnly} label="Neutral script only" />
            <ChatToggleButton open={chatOpen} onClick={() => setChatOpen((v) => !v)} />
          </div>
        </div>
      </div>

      <div className="p-4 max-w-[1700px] mx-auto space-y-4">
        {loading && <div className="text-text-dim text-sm">Loading…</div>}
        {error && <div className="text-error text-sm">{error}</div>}

        {data && (
          <>
            {/* 2. Identity header -- spans the full width, above both columns -- */}
            <div className="rounded-lg border border-border bg-bg-card p-4">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                  <div className="text-2xl font-bold">{data.team}</div>
                  <div className="text-sm text-text-muted">
                    {data.season} · weeks {data.weeks[0]}–{data.weeks[1]} · record {data.header.record ?? '—'}
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
                  <MetricChip label={neutralOnly ? 'EPA/play (neutral)' : 'EPA/play'} obj={data.splits[activeAll].epa_per_play} size="lg" />
                  <MetricChip label={neutralOnly ? 'PROE (neutral)' : 'PROE'} obj={data.splits[activeAll].proe} fmt={(v) => fmtPct(v)} size="lg" />
                  <MetricChip label="Pace sec/snap" obj={data.header.pace} fmt={(v) => fmtNum(v, 1)} size="lg" />
                  <MetricChip label="Plays/game" obj={data.header.plays_per_game} fmt={(v) => fmtNum(v, 1)} size="lg" />
                </div>
              </div>
              <div className="mt-3 text-sm text-text-muted italic">
                {buildBlurb(data.splits[activeAll].epa_per_play, data.splits[activeAll].proe, data.header.pace)}
              </div>
            </div>

            {/* Two-column body: main stack (efficiency/neutral/situational/personnel/trend)
                left, League Context sticky alongside on the right. */}
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_460px] gap-4 items-start">
              <div className="space-y-4 min-w-0">
                {/* 3. Efficiency grid 3x3 -------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">Efficiency (All / Pass / Rush)</div>
                  <div className="grid grid-cols-3 gap-3">
                    {([
                      ['All', activeAll, 'cpoe' as const, 'CPOE', (v: number | null) => fmtNum(v, 1)],
                      ['Pass', activePass, 'explosive_rate' as const, 'Explosive %', fmtPct],
                      ['Rush', activeRush, 'explosive_rate' as const, 'Explosive Rush %', fmtPct],
                    ] as const).map(([rowLabel, split, secondaryKey, secondaryLabel, secondaryFmt]) => {
                      const m = data.splits[split];
                      return (
                        <div key={rowLabel} className="rounded-md border border-border-subtle p-3">
                          <div className="text-xs font-semibold text-text-muted mb-2">{rowLabel}</div>
                          <div className="grid grid-cols-1 gap-2">
                            <MetricChip label="EPA/play" obj={m?.epa_per_play} size="sm" />
                            <MetricChip label="Success rate" obj={m?.success_rate} fmt={fmtPct} size="sm" />
                            <MetricChip label={secondaryLabel} obj={m?.[secondaryKey]} fmt={secondaryFmt} size="sm" />
                            {/* trend is only computed for the all/neutral split's EPA (spec section 8) --
                                reused here as the row sparkline for all three rows, a documented Phase 2
                                simplification rather than adding per-split trend series. */}
                            {data.trend.epa_play.length > 1 && (
                              <Sparkline data={data.trend.epa_play} color={PCT_GREEN} />
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* 4. Neutral script strip -------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">
                    Neutral Script (all vs neutral)
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <DeltaChip label="EPA/play" allObj={data.splits.all.epa_per_play} neutralObj={data.splits.neutral.epa_per_play} fmt={fmtNum} />
                    <DeltaChip label="Success rate" allObj={data.splits.all.success_rate} neutralObj={data.splits.neutral.success_rate} fmt={fmtPct} />
                    <DeltaChip label="Pass rate (PROE)" allObj={data.splits.all.proe} neutralObj={data.splits.neutral.proe} fmt={fmtPct} />
                    <MetricChip label="Sec/snap" obj={data.splits.neutral.sec_per_snap} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="No-huddle rate" obj={data.splits.neutral.no_huddle_rate} fmt={fmtPct} size="sm" />
                  </div>
                </div>

                {/* 5. Situational row --------------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">Situational</div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <MetricChip label="Early-down pass %" obj={data.splits[activeAll].early_down_pass_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="3rd down conv" obj={data.splits[activeAll].third_down_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="RZ TD%" obj={data.splits[activeAll].rz_td_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="Pts/drive" obj={data.splits[activeAll].pts_per_drive} fmt={(v) => fmtNum(v, 2)} size="sm" />
                    <MetricChip label="Drive success" obj={data.splits[activeAll].drive_success} fmt={fmtPct} size="sm" />
                    <MetricChip label="PA rate" obj={data.splits[activePass].pa_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="PA EPA" obj={data.splits[activePass].pa_epa} fmt={(v) => fmtNum(v, 2)} size="sm" />
                    <MetricChip label="Screen rate" obj={data.splits[activePass].screen_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="aDOT" obj={data.splits[activePass].adot} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Sack rate" obj={data.splits[activePass].sack_rate} fmt={fmtPct} size="sm" />
                    <MetricChip label="Pass-block grade" obj={data.context.pass_block_grade} fmt={(v) => fmtNum(v, 1)} size="sm" />
                    <MetricChip label="Pressure rate allowed (season)" obj={data.context.pressure_rate_allowed} fmt={fmtRawPct} size="sm" />
                  </div>
                </div>

                {/* 6. Personnel panel (Phase 3, conditional) ---------------------- */}
                <PersonnelPanel personnel={data.personnel} coverage={data.personnel_coverage} />

                {/* 8. Trend footer -------------------------------------------------- */}
                <div className="rounded-lg border border-border bg-bg-card p-4">
                  <div className="text-xs uppercase tracking-wider text-text-dim mb-3">
                    Trend (dashed = league median)
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                    <TrendCard label="EPA/play" series={data.trend.epa_play} median={data.trend_league_median.epa_play} />
                    <TrendCard label="PROE" series={data.trend.proe} median={data.trend_league_median.proe} />
                    <TrendCard label="Success rate" series={data.trend.success_rate} median={data.trend_league_median.success_rate} />
                    <TrendCard label="Pace sec/snap" series={data.trend.pace} median={data.trend_league_median.pace} />
                    <TrendCard label="Explosive rate" series={data.trend.explosive_rate} median={data.trend_league_median.explosive_rate} />
                  </div>
                </div>
              </div>

              {/* Right column: target rate by position, then League Context below it --
                  sticky together while scrolling the left stack. */}
              <div className="lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-88px)] lg:overflow-y-auto space-y-4">
                <TargetRateByPosition rates={data.target_rate_by_position} />

                {/* 7. League context */}
                <LeagueTable rows={data.league_table} selectedTeam={data.team} />
              </div>
            </div>
          </>
        )}
      </div>

      <OffenvChatDrawer open={chatOpen} onClose={() => setChatOpen(false)} dashboardData={data} />
    </div>
  );
}

function DeltaChip({
  label, allObj, neutralObj, fmt,
}: {
  label: string;
  allObj: MetricObj;
  neutralObj: MetricObj;
  fmt: (v: number | null) => string;
}) {
  const delta = allObj.v != null && neutralObj.v != null ? neutralObj.v - allObj.v : null;
  const arrow = delta == null ? '' : delta > 0 ? '▲' : delta < 0 ? '▼' : '—';
  const arrowColor = delta == null ? PCT_NEUTRAL : delta > 0 ? PCT_GREEN : delta < 0 ? PCT_RED : PCT_NEUTRAL;
  return (
    <div className="rounded-md border border-border bg-bg-card px-3 py-2">
      <div className="text-[9px] uppercase tracking-wider text-text-dim">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className="text-sm text-text-muted">{fmt(allObj.v)}</span>
        <span style={{ color: arrowColor }} className="text-xs">{arrow}</span>
        <span className="text-sm font-semibold">{fmt(neutralObj.v)}</span>
      </div>
      <div className="text-[9px] text-text-dim mt-1">all → neutral</div>
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

// Distinct categorical colors for the personnel stacked bar (not the
// percentile ramp -- this is a category breakdown, not a good/bad value).
const PERSONNEL_COLORS: Record<string, string> = {
  '11': catColor(0), '12': catColor(2), '21': catColor(1),
  '13': catColor(4), '10': catColor(3), '22': catColor(5),
  other: token('tx-dim'),
};

function PersonnelPanel({
  personnel, coverage,
}: {
  personnel: PersonnelRow[];
  coverage: { weeks_present: number[]; weeks_missing: number[] };
}) {
  if (personnel.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-bg-card p-4">
        <div className="text-xs uppercase tracking-wider text-text-dim mb-2">Personnel</div>
        <div className="text-sm text-text-dim">
          No personnel data for the selected week range.
        </div>
      </div>
    );
  }
  const snapShareSum = personnel.reduce((s, p) => s + p.snap_share, 0);
  return (
    <div className="rounded-lg border border-border bg-bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase tracking-wider text-text-dim">Personnel</div>
        {coverage.weeks_missing.length > 0 && (
          <div className="text-[10px] text-warn">
            missing weeks: {coverage.weeks_missing.join(', ')} (degraded -- personnel data unavailable those weeks)
          </div>
        )}
      </div>

      {/* horizontal stacked usage bar */}
      <div className="h-6 w-full rounded-md overflow-hidden flex border border-border-subtle" title={`sums to ${(snapShareSum * 100).toFixed(1)}%`}>
        {personnel.map((p) => (
          <div
            key={p.grp}
            style={{ width: `${p.snap_share * 100}%`, backgroundColor: PERSONNEL_COLORS[p.grp] ?? PERSONNEL_COLORS.other }}
            title={`${p.grp}: ${(p.snap_share * 100).toFixed(1)}%`}
          />
        ))}
      </div>

      {/* per-grouping mini-cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 mt-3">
        {personnel.map((p) => (
          <div key={p.grp} className="rounded-md border border-border-subtle p-2">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: PERSONNEL_COLORS[p.grp] ?? PERSONNEL_COLORS.other }} />
              <span className="text-xs font-semibold">{p.grp === 'other' ? 'Other' : p.grp}</span>
              {p.pct_usage != null && (
                <span className="text-[9px] text-text-dim ml-auto">{p.pct_usage}pct usage</span>
              )}
            </div>
            <div className="text-[10px] text-text-dim">Snap share</div>
            <div className="text-sm font-semibold">{fmtPct(p.snap_share)}</div>
            <div className="text-[10px] text-text-dim mt-1">Pass rate</div>
            <div className="text-xs">{fmtPct(p.pass_rate)}</div>
            <div className="text-[10px] text-text-dim mt-1">EPA/play</div>
            <div className="text-xs" style={{ color: pctColor(p.pct_usage) }}>{fmtNum(p.epa_play, 2)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

const TARGET_RATE_COLORS: Record<'RB' | 'WR' | 'TE', string> = {
  // Locked to the app-wide position legend; this map used to disagree
  // with it (WR was the accent, TE was blue).
  RB: posColor('RB'), WR: posColor('WR'), TE: posColor('TE'),
};

function TargetRateByPosition({ rates }: { rates: TargetRateByPositionData }) {
  const positions: ('RB' | 'WR' | 'TE')[] = ['RB', 'WR', 'TE'];
  const hasData = positions.some((p) => rates[p]?.v != null);
  return (
    <div className="rounded-lg border border-border bg-bg-card p-4">
      <div className="text-xs uppercase tracking-wider text-text-dim mb-3">Target Rate by Position</div>
      {!hasData ? (
        <div className="text-sm text-text-dim">No target data for the selected week range.</div>
      ) : (
        <>
          <div className="h-4 w-full rounded-md overflow-hidden flex border border-border-subtle mb-3">
            {positions.map((p) => (
              <div
                key={p}
                style={{ width: `${(rates[p]?.v ?? 0) * 100}%`, backgroundColor: TARGET_RATE_COLORS[p] }}
                title={`${p}: ${fmtPct(rates[p]?.v ?? null)}`}
              />
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            {positions.map((p) => (
              <div key={p} className="rounded-md border border-border-subtle p-2">
                <div className="flex items-center justify-between gap-1 mb-1">
                  <div className="flex items-center gap-1.5">
                    <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: TARGET_RATE_COLORS[p] }} />
                    <span className="text-xs font-semibold">{p}</span>
                  </div>
                  {rates[p]?.rank != null && rates[p]?.n_teams != null && (
                    <span className="text-[9px] text-text-dim tabular-nums">#{rates[p]!.rank}/{rates[p]!.n_teams}</span>
                  )}
                </div>
                <div
                  className="text-lg font-semibold tabular-nums"
                  style={{ color: pctColor(rates[p]?.pct ?? null) }}
                >
                  {fmtPct(rates[p]?.v ?? null)}
                </div>
                {rates[p]?.pct != null ? (
                  <div className="mt-1 h-1 rounded-full bg-bg-elevated overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${rates[p]!.pct}%`, backgroundColor: pctColor(rates[p]!.pct) }}
                    />
                  </div>
                ) : (
                  <div className="mt-1 text-[9px] text-text-dim">n/a</div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function LeagueTable({ rows, selectedTeam }: { rows: TeamOffenseEnvResponse['league_table']; selectedTeam: string }) {
  const [sortKey, setSortKey] = useState<'epa_play' | 'proe' | 'pace' | 'success_rate'>('epa_play');
  const sorted = useMemo(
    () => [...rows].sort((a, b) => (b[sortKey] ?? -Infinity) - (a[sortKey] ?? -Infinity)),
    [rows, sortKey],
  );
  const cols: { key: typeof sortKey; label: string; fmt: (v: number | null) => string }[] = [
    { key: 'epa_play', label: 'EPA/play', fmt: (v) => fmtNum(v, 3) },
    { key: 'proe', label: 'PROE', fmt: fmtPct },
    { key: 'pace', label: 'Sec/snap', fmt: (v) => fmtNum(v, 1) },
    { key: 'success_rate', label: 'Success %', fmt: fmtPct },
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
