import { cn } from '@/lib/utils';
import {
  dashboardIdpAlignment,
  type DashIdpAlignment,
  type DashIdpChip,
  type DashAlignmentSeg,
  type DashRoleSeg,
} from '@/lib/dashboardApi';
import { useEffect, useState } from 'react';

// ---------------------------------------------------------------------------
// IDP Alignment Profile (Player Profile Sections Phase 3, P3.1/P3.4).
// Defender-only (DE/DT/LB/CB/S). Same mutually-exclusive left-column slot as
// RouteTree/QbPassingProfile/RbRushingProfile, gated on position_group.
//
// Redesigned (2026-07-08, post-QA feedback) from a pair of thin stacked
// percentage pills -- which read as flat/abstract next to the QB zone grid
// and RB lane strip's field-shaped visuals -- into a schematic top-down
// defensive-formation diagram: the 5 alignment buckets sit where they
// actually occur on a field (D-Line at the LOS, Box just off it, Slot/Wide
// Corner outside at intermediate depth, Free Safety deep middle), circle
// size + fill intensity both encoding share. Deepest at top, LOS at bottom,
// matching QbPassingProfile's existing depth convention. All 5 zones always
// show a label (even nonzero-but-small ones -- a floor radius keeps them
// visible), fixing the old version's >=8%-to-label cutoff that made small
// segments disappear.
//
// Role (run defense / pass rush / coverage) stays a stacked bar -- 3
// categories is a fine fit for that shape -- but with always-visible labels
// (no threshold gate) and higher-contrast segment colors.
//
// Both are ORTHOGONAL splits of the same snap total (spec P3.6) and stay
// visually separate sections, never combined into one chart.
// ---------------------------------------------------------------------------

type AlignKey = DashAlignmentSeg['bucket'];

const ALIGNMENT_LABEL: Record<AlignKey, string> = {
  fs: 'Free Safety', slot: 'Slot', corner: 'Wide Corner', box: 'Box', dl: 'D-Line',
};

// normalized viewBox positions -- deepest at top (y small), LOS at bottom
const ALIGNMENT_POS: Record<AlignKey, { x: number; y: number }> = {
  fs: { x: 150, y: 46 },
  slot: { x: 78, y: 152 },
  corner: { x: 222, y: 152 },
  box: { x: 150, y: 240 },
  dl: { x: 150, y: 312 },
};

const ROLE_LABEL: Record<DashRoleSeg['bucket'], string> = {
  run_defense: 'Run Defense', pass_rush: 'Pass Rush', coverage: 'Coverage',
};
const ROLE_COLOR: Record<DashRoleSeg['bucket'], string> = {
  run_defense: 'var(--cat-3)', pass_rush: 'var(--mid)', coverage: 'var(--accent)',
};
const ROLE_TEXT: Record<DashRoleSeg['bucket'], string> = {
  run_defense: 'var(--tx)', pass_rush: 'var(--bg)', coverage: 'var(--bg)',
};

const MIN_RADIUS = 12;
const MAX_RADIUS = 54;

function zoneRadius(share: number): number {
  // area-proportional-ish (sqrt), floored so every nonzero zone stays visible
  if (share <= 0) return MIN_RADIUS * 0.55;
  return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(share);
}

function zoneFill(share: number): string {
  const t = Math.min(1, share / 0.6); // saturate toward max around 60% share
  const light = Math.round(22 + t * 34);
  const sat = Math.round(45 + t * 35);
  return `hsl(160 ${sat}% ${light}%)`;
}

type ChipKey = keyof NonNullable<DashIdpAlignment['header']>;

const ALL_CHIPS: { key: ChipKey; label: string }[] = [
  { key: 'tackle_opp_rate', label: 'Tackle Opp Rate' },
  { key: 'missed_tackle_rate', label: 'Missed Tackle %' },
  { key: 'pressure_rate', label: 'Pressure Rate' },
  { key: 'coverage_eff', label: 'Yds/Cov Snap' },
  { key: 'fp_per_snap', label: 'FP/Snap' },
];

// spec: "pressure rate for DL/EDGE, coverage for DBs, both for LBs"
function chipsForPosition(group: string | undefined): ChipKey[] {
  if (group === 'DE' || group === 'DT') {
    return ['tackle_opp_rate', 'missed_tackle_rate', 'pressure_rate', 'fp_per_snap'];
  }
  if (group === 'CB' || group === 'S') {
    return ['tackle_opp_rate', 'missed_tackle_rate', 'coverage_eff', 'fp_per_snap'];
  }
  return ['tackle_opp_rate', 'missed_tackle_rate', 'pressure_rate', 'coverage_eff', 'fp_per_snap'];
}

function fmtChipValue(key: ChipKey, v: number): string {
  if (key === 'tackle_opp_rate') return `${(v * 100).toFixed(0)}%`;
  if (key === 'missed_tackle_rate') return `${v.toFixed(1)}%`;
  if (key === 'pressure_rate') return `${(v * 100).toFixed(0)}%`;
  if (key === 'coverage_eff') return v.toFixed(2);
  return v.toFixed(3);
}

export default function IdpAlignmentProfile({
  playerId,
  season,
  bucket,
  leagueId,
}: {
  playerId: string;
  season: number;
  bucket: string | null;
  leagueId?: string | null;
}) {
  const [data, setData] = useState<DashIdpAlignment | null>(null);
  const [loading, setLoading] = useState(false);
  const [hoverAlign, setHoverAlign] = useState<AlignKey | null>(null);
  const [hoverRole, setHoverRole] = useState<string | null>(null);

  const isDefender = bucket === 'DE' || bucket === 'DT' || bucket === 'LB'
    || bucket === 'CB' || bucket === 'S';

  useEffect(() => {
    if (!playerId || !isDefender) { setData(null); return; }
    let cancelled = false;
    setLoading(true);
    setHoverAlign(null);
    setHoverRole(null);
    dashboardIdpAlignment(playerId, season, leagueId)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [playerId, season, leagueId, isDefender]);

  if (!isDefender) return null;

  const chipKeys = chipsForPosition(data?.position_group);
  const alignByKey = new Map((data?.alignment ?? []).map((a) => [a.bucket, a]));
  const hoveredAlign = hoverAlign ? alignByKey.get(hoverAlign) : null;
  const hoveredRole = hoverRole
    ? data?.role?.find((r) => r.bucket === hoverRole) : null;

  return (
    <div className="rounded-xl border border-border bg-bg-card p-4 w-full flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="text-[10px] uppercase tracking-wider text-text-muted">
          Alignment Profile · {season}
          {data?.eligible && data.total_snaps != null ? ` · ${data.total_snaps} snaps` : ''}
        </div>
      </div>

      {data?.eligible && (
        <div
          className={cn('grid gap-2 mb-3 shrink-0', chipKeys.length === 5 ? 'grid-cols-5' : 'grid-cols-4')}
        >
          {chipKeys.map((key) => {
            const label = ALL_CHIPS.find((c) => c.key === key)?.label ?? key;
            const chip = data.header?.[key] as DashIdpChip | null | undefined;
            return <ChipCard key={key} label={label} chipKey={key} chip={chip ?? null} />;
          })}
        </div>
      )}

      <div className="relative w-full flex-1 min-h-0 flex flex-col items-center justify-center">
        {loading && !data ? (
          <div className="text-text-dim text-sm">Loading alignment profile…</div>
        ) : !data?.eligible ? (
          <div className="text-text-dim/70 text-xs text-center px-4">
            {data?.reason ?? `No ${season} alignment profile data.`}
          </div>
        ) : (
          <>
            {/* Role (what the snap was used for: run defense / pass rush /
                coverage) leads, above the alignment diagram -- the type-of-
                snap breakdown is the first read, not something you have to
                scroll past the field diagram to find. */}
            <div className="relative w-full shrink-0 mb-3">
              <div className="text-xs uppercase tracking-wider text-text-dim mb-1.5">Role</div>
              <StackedBar
                segments={(data.role ?? []).map((s) => ({
                  key: s.bucket, share: s.share, snaps: s.snaps,
                  label: ROLE_LABEL[s.bucket], color: ROLE_COLOR[s.bucket], textColor: ROLE_TEXT[s.bucket],
                }))}
                hoverKey={hoverRole}
                onHover={setHoverRole}
              />
              {/* absolutely positioned, NOT inline -- an inline reveal here
                  would push the alignment diagram below it down/up on every
                  hover. Matches the hoveredAlign tooltip's pattern below. */}
              {hoveredRole && (
                <div
                  className="pointer-events-none absolute z-10 mt-1.5 rounded-md border border-border
                             bg-bg-card px-2.5 py-1.5 text-xs shadow-xl shadow-black/50"
                  style={{ left: 0, top: '100%' }}
                >
                  <span className="font-semibold text-text">{ROLE_LABEL[hoveredRole.bucket]}</span>
                  <span className="text-text-muted">
                    {' · '}{hoveredRole.snaps} snaps ({(hoveredRole.share * 100).toFixed(0)}%)
                  </span>
                </div>
              )}
              <div className="mt-1.5 text-xs text-text-muted text-center">
                circle size = share of snaps at that alignment · role bar = what the snap was used for (orthogonal split)
              </div>
            </div>

            <div className="w-full flex-1 min-h-0 flex items-center justify-center">
              <svg viewBox="0 0 300 340" className="w-full h-full max-w-[340px]" preserveAspectRatio="xMidYMid meet">
                <line x1={20} y1={278} x2={280} y2={278} stroke="rgb(255 255 255 / 0.25)" strokeWidth={2} strokeDasharray="6 4" />
                <text x={20} y={272} fontSize={9} fill="var(--tx-mut)">LOS</text>
                <text x={150} y={16} textAnchor="middle" fontSize={9} fill="var(--tx-mut)" style={{ textTransform: 'uppercase', letterSpacing: 1 }}>Deep</text>

                {(Object.keys(ALIGNMENT_POS) as AlignKey[]).map((key) => {
                  const seg = alignByKey.get(key);
                  const share = seg?.share ?? 0;
                  const pos = ALIGNMENT_POS[key];
                  const r = zoneRadius(share);
                  const isHovered = hoverAlign === key;
                  return (
                    <g key={key}>
                      <circle
                        cx={pos.x} cy={pos.y} r={r}
                        fill={zoneFill(share)}
                        stroke={isHovered ? 'var(--accent)' : 'rgb(255 255 255 / 0.15)'}
                        strokeWidth={isHovered ? 2.5 : 1}
                        style={{ cursor: 'pointer' }}
                        onMouseEnter={() => setHoverAlign(key)}
                        onMouseLeave={() => setHoverAlign(null)}
                      />
                      <text
                        x={pos.x} y={pos.y + 4} textAnchor="middle" fontSize={13} fontWeight={700}
                        fill="var(--tx)" pointerEvents="none"
                      >
                        {Math.round(share * 100)}%
                      </text>
                      <text
                        x={pos.x} y={pos.y + r + 15} textAnchor="middle" fontSize={9.5} fill="var(--tx-mut)"
                        pointerEvents="none"
                      >
                        {ALIGNMENT_LABEL[key]}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>

            {hoveredAlign && (
              <div
                className="pointer-events-none absolute z-10 rounded-md border border-border
                           bg-bg-card px-2.5 py-1.5 text-xs shadow-xl shadow-black/50"
                style={{ left: 12, bottom: 12 }}
              >
                <div className="text-text font-semibold">{ALIGNMENT_LABEL[hoveredAlign.bucket]}</div>
                <div className="text-text-muted tabular-nums mt-0.5">
                  {hoveredAlign.snaps} snaps ({(hoveredAlign.share * 100).toFixed(0)}%)
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function StackedBar({
  segments, hoverKey, onHover,
}: {
  segments: { key: string; share: number; snaps: number; label: string; color: string; textColor: string }[];
  hoverKey: string | null;
  onHover: (key: string | null) => void;
}) {
  return (
    <div className="flex w-full h-9 rounded-md overflow-hidden border border-border">
      {segments.map((s) => (
        <div
          key={s.key}
          className="h-full flex items-center justify-center relative"
          style={{
            width: `${Math.max(s.share * 100, s.snaps > 0 ? 3 : 0)}%`,
            backgroundColor: s.color,
            outline: hoverKey === s.key ? '2px solid var(--tx)' : 'none',
            outlineOffset: -2,
            cursor: 'pointer',
          }}
          onMouseEnter={() => onHover(s.key)}
          onMouseLeave={() => onHover(null)}
        >
          <span
            className="text-sm font-bold tabular-nums pointer-events-none whitespace-nowrap px-1"
            style={{ color: s.textColor }}
          >
            {Math.round(s.share * 100)}%
          </span>
        </div>
      ))}
    </div>
  );
}

// Same percentile-fill-bar convention as the other profile chips.
function ChipCard({
  label, chipKey, chip,
}: { label: string; chipKey: ChipKey; chip: DashIdpChip | null }) {
  const pct = chip?.pct;
  const hue = pct != null ? Math.max(0, Math.min(120, pct * 1.2)) : 0;
  const fill = `hsl(${hue} 70% 50%)`;
  return (
    <div className="rounded-lg border border-border bg-bg-elevated/40 p-2">
      <div className="text-[8.5px] uppercase tracking-wider text-text-dim mb-0.5 truncate">{label}</div>
      <div className="text-base font-semibold tabular-nums text-text leading-none">
        {chip ? fmtChipValue(chipKey, chip.value) : '—'}
      </div>
      {pct != null ? (
        <div className="mt-1" title={`${pct}th percentile within the eligible pool`}>
          <div className="relative h-1 rounded-full bg-bg-elevated overflow-hidden">
            <div
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ width: `${pct}%`, backgroundColor: fill }}
            />
          </div>
          <div className={cn('mt-0.5 text-[9px] font-semibold tabular-nums')} style={{ color: fill }}>
            {pct}th
          </div>
        </div>
      ) : (
        <div className="mt-1 text-[9px] text-text-dim">—</div>
      )}
    </div>
  );
}
