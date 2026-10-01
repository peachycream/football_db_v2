import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  dashboardQbZones,
  type DashQbZones,
  type DashQbZone,
  type DashQbChip,
} from '@/lib/dashboardApi';

// ---------------------------------------------------------------------------
// QB Passing Profile (Player Profile Sections Phase 1, §1/§8). QB-only.
// Redesigned (2026-07-08 layout pass) to fill the same "primary vertical
// visual" slot RouteTree occupies for receivers -- responsive field grid via
// ResizeObserver (was a fixed 300x340 SVG that left dead space once the
// component moved out of the old full-width row), percentile chips as a
// compact strip above the grid rather than beside it.
//
// Field grid: vertical field graphic, LOS at the bottom, depth increasing
// upward (blos -> short -> medium -> deep), 3 columns (left/middle/right).
// Zone fill = diverging scale on zone CPOE, clamped ±10pp, green hot / red
// cold, neutral near 0. Low-sample zones (<8 attempts) render desaturated
// with an em-dash CPOE in the tooltip.
// ---------------------------------------------------------------------------

const LOW_SAMPLE = 8;
const CPOE_CLAMP = 10;
const DEPTH_ORDER: DashQbZone['depth'][] = ['deep', 'medium', 'short', 'blos']; // top -> bottom
const DEPTH_LABEL: Record<DashQbZone['depth'], string> = {
  deep: '20+', medium: '10-19', short: '0-9', blos: 'Behind LOS',
};
const DIRECTIONS: DashQbZone['direction'][] = ['left', 'middle', 'right'];

function zoneColor(cpoe: number | null, lowSample: boolean): string {
  if (lowSample || cpoe == null) return 'var(--surf-3)';
  const c = Math.max(-CPOE_CLAMP, Math.min(CPOE_CLAMP, cpoe));
  const t = Math.abs(c) / CPOE_CLAMP;
  const hue = c >= 0 ? 120 : 0;
  const sat = Math.round(15 + t * 65);
  const light = Math.round(14 + t * 26);
  return `hsl(${hue} ${sat}% ${light}%)`;
}

const CHIP_LABELS: { key: keyof NonNullable<DashQbZones['header']>; label: string }[] = [
  { key: 'epa_per_dropback', label: 'EPA/Dropback' },
  { key: 'cpoe', label: 'CPOE' },
  { key: 'success_rate', label: 'Success Rate' },
  { key: 'fp_per_dropback', label: 'FP/Dropback' },
];

function fmtChipValue(key: string, v: number): string {
  if (key === 'cpoe') return `${v >= 0 ? '+' : ''}${v.toFixed(1)}`;
  if (key === 'success_rate') return `${(v * 100).toFixed(0)}%`;
  return v.toFixed(2);
}

export default function QbPassingProfile({
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
  const [data, setData] = useState<DashQbZones | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<{ direction: string; depth: string } | null>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const wrapRef = useRef<HTMLDivElement>(null);

  const isQb = bucket === 'QB';

  useEffect(() => {
    if (!playerId || !isQb) { setData(null); return; }
    let cancelled = false;
    setLoading(true);
    setHover(null);
    dashboardQbZones(playerId, season, leagueId)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [playerId, season, leagueId, isQb]);

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setDims({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) });
      }
    });
    ro.observe(el);
    const r = el.getBoundingClientRect();
    setDims({ w: Math.floor(r.width), h: Math.floor(r.height) });
    return () => ro.disconnect();
  }, [isQb]);

  const zoneMap = useMemo(
    () => new Map((data?.zones ?? []).map((z) => [`${z.direction}|${z.depth}`, z])),
    [data],
  );

  // grid geometry: fills the wrapper, 3 cols x 4 rows, capped so it doesn't
  // sprawl on ultra-tall narrow screens
  const layout = useMemo(() => {
    if (!dims.w || !dims.h) return null;
    // wide enough for the longest row label, 'Behind LOS' (~53px at 10.5px): at 56 the
    // right-anchored label started at x=-3 and the SVG edge clipped it (v2, 2026-09-30).
    const labelColW = 76;
    const dirLabelH = 18;
    const gridW = Math.max(180, dims.w - labelColW);
    const gridH = Math.max(240, Math.min(dims.h - dirLabelH - 10, 640));
    const colW = gridW / 3;
    const rowH = gridH / 4;
    return { gridW, gridH, colW, rowH, labelColW, dirLabelH };
  }, [dims]);

  if (!isQb) return null;

  return (
    <div className="rounded-xl border border-border bg-bg-card p-4 w-full flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="text-[10px] uppercase tracking-wider text-text-muted">
          Passing Profile · {season}
          {data?.eligible && data.dropbacks != null ? ` · ${data.dropbacks} dropbacks` : ''}
        </div>
      </div>

      {/* percentile chip strip — only once real eligible data exists */}
      {data?.eligible && (
        <div className="grid grid-cols-4 gap-2 mb-3 shrink-0">
          {CHIP_LABELS.map(({ key, label }) => {
            const chip = data.header?.[key] as DashQbChip | null | undefined;
            return <ChipCard key={key} label={label} chipKey={key} chip={chip ?? null} />;
          })}
        </div>
      )}

      {/* legend leads, above the field grid -- matches the IDP Alignment
          Profile's Role-bar-at-top layout, not buried below the diagram. */}
      {data?.eligible && (
        <div className="mb-2 text-xs text-text-muted text-center shrink-0">
          fill = CPOE (green hot / red cold, ±{CPOE_CLAMP}pp) · label = attempt share
        </div>
      )}

      {/* field grid wrapper — ALWAYS rendered (unconditionally, matching
          RouteTree's pattern) so the ResizeObserver in useLayoutEffect has a
          real DOM node to attach to on mount, before `data` has loaded. Only
          the CONTENT inside is conditional on loading/eligibility. Making
          this whole div conditional on `data?.eligible` was the original bug
          -- wrapRef.current was null when the effect ran (data hadn't
          loaded yet), so the observer never attached and the grid never
          rendered even once data arrived. */}
      <div
        ref={wrapRef}
        className="relative w-full flex-1 min-h-0 flex flex-col items-center justify-center"
      >
        {loading && !data ? (
          <div className="text-text-dim text-sm">Loading passing profile…</div>
        ) : !data?.eligible ? (
          <div className="text-text-dim/70 text-xs text-center px-4">
            {data?.reason ?? `No ${season} passing profile data.`}
          </div>
        ) : (
          <>
            {layout && (
              <svg width={layout.gridW + layout.labelColW} height={layout.gridH + layout.dirLabelH} className="block">
                {/* LOS sits between the 0-9 row and the Behind-LOS row (blos is
                    NEGATIVE depth, so it belongs below the line, not above it).
                    3 rows of DEPTH_ORDER (deep/medium/short) precede it. */}
                <line
                  x1={layout.labelColW} y1={layout.dirLabelH + 3 * layout.rowH}
                  x2={layout.gridW + layout.labelColW} y2={layout.dirLabelH + 3 * layout.rowH}
                  stroke="rgb(255 255 255 / 0.25)" strokeWidth={2}
                />
                {/* centred ON the line (it labels the line), not sitting above it inside
                    the 0-9 row where it read as a second 0-9 label */}
                <text
                  x={layout.labelColW - 6} y={layout.dirLabelH + 3 * layout.rowH}
                  textAnchor="end" dominantBaseline="middle" fontSize={11} fontWeight={600}
                  fill="var(--tx-mut)"
                >
                  LOS
                </text>

                {DIRECTIONS.map((direction, colIdx) => (
                  <text
                    key={direction}
                    x={layout.labelColW + colIdx * layout.colW + layout.colW / 2}
                    y={layout.dirLabelH - 6}
                    textAnchor="middle" fontSize={11.5} fill="var(--tx-mut)"
                    style={{ textTransform: 'capitalize' }}
                  >
                    {direction}
                  </text>
                ))}

                {DEPTH_ORDER.map((depth, rowIdx) => {
                  const y = layout.dirLabelH + rowIdx * layout.rowH;
                  return (
                    <g key={depth}>
                      <text
                        x={layout.labelColW - 6} y={y + layout.rowH / 2 + 3}
                        textAnchor="end" fontSize={10.5} fill="var(--tx-mut)"
                      >
                        {DEPTH_LABEL[depth]}
                      </text>
                      {DIRECTIONS.map((direction, colIdx) => {
                        const x = layout.labelColW + colIdx * layout.colW;
                        const z = zoneMap.get(`${direction}|${depth}`);
                        const attempts = z?.attempts ?? 0;
                        const low = attempts < LOW_SAMPLE;
                        const fill = zoneColor(z?.cpoe ?? null, low);
                        const isHovered = hover?.direction === direction && hover?.depth === depth;
                        return (
                          <g key={`${direction}-${depth}`}>
                            <rect
                              x={x + 2} y={y + 3} width={layout.colW - 4} height={layout.rowH - 6}
                              fill={fill}
                              stroke={isHovered ? 'var(--accent)' : 'rgb(255 255 255 / 0.08)'}
                              strokeWidth={isHovered ? 2 : 1}
                              opacity={low ? 0.55 : 1}
                              rx={4}
                              style={{ cursor: 'pointer' }}
                              onMouseEnter={() => setHover({ direction, depth })}
                              onMouseLeave={() => setHover(null)}
                            />
                            {isHovered && z ? (
                              // metrics render IN the hovered box rather than in a
                              // fixed corner tooltip -- keeps the reader's eye where
                              // the cursor already is. Built as a line array so the
                              // stack stays vertically centered whether it ends up
                              // 3 or 4 lines tall (a fixed set of offsets biased the
                              // block downward and overflowed short rows).
                              <g pointerEvents="none">
                                {(() => {
                                  const lines: { t: string; size: number; fill: string; bold?: boolean }[] = [
                                    {
                                      t: `${Math.round((z.att_share ?? 0) * 100)}% · ${z.attempts} att`,
                                      size: 12.5, fill: 'var(--tx)', bold: true,
                                    },
                                    {
                                      t: attempts >= LOW_SAMPLE
                                        ? `${((z.comp_pct ?? 0) * 100).toFixed(0)}% comp`
                                        : 'comp% —',
                                      size: 11.5, fill: 'var(--tx)',
                                    },
                                    {
                                      t: `CPOE ${attempts >= LOW_SAMPLE && z.cpoe != null
                                        ? `${z.cpoe >= 0 ? '+' : ''}${z.cpoe.toFixed(1)}`
                                        : '—'}`,
                                      size: 11.5, fill: 'var(--tx)',
                                    },
                                  ];
                                  if (attempts < LOW_SAMPLE) {
                                    lines.push({ t: 'small sample', size: 10.5, fill: 'var(--mid)' });
                                  } else if (z.epa_per_att != null) {
                                    lines.push({
                                      t: `${z.epa_per_att.toFixed(2)} EPA/att`, size: 11, fill: 'var(--tx-mut)',
                                    });
                                  }
                                  // line pitch shrinks if the row is too short to
                                  // seat the stack at the comfortable 14px spacing
                                  const pitch = Math.min(14, (layout.rowH - 12) / lines.length);
                                  const cy = y + layout.rowH / 2;
                                  const top = cy - ((lines.length - 1) * pitch) / 2;
                                  return lines.map((ln, i) => (
                                    <text
                                      key={ln.t}
                                      x={x + layout.colW / 2}
                                      y={top + i * pitch + 4}
                                      textAnchor="middle"
                                      fontSize={ln.size}
                                      fontWeight={ln.bold ? 600 : undefined}
                                      fill={ln.fill}
                                    >
                                      {ln.t}
                                    </text>
                                  ));
                                })()}
                              </g>
                            ) : (
                              <text
                                x={x + layout.colW / 2} y={y + layout.rowH / 2 + 4}
                                textAnchor="middle" fontSize={15} fontWeight={600}
                                fill="var(--tx)" pointerEvents="none"
                              >
                                {attempts > 0 ? `${Math.round((z?.att_share ?? 0) * 100)}%` : '—'}
                              </text>
                            )}
                          </g>
                        );
                      })}
                    </g>
                  );
                })}
              </svg>
            )}

          </>
        )}
      </div>
    </div>
  );
}

// Same percentile-fill-bar convention as PlayerDashboard's PercentileBar,
// adapted into a compact chip card for the strip above the field grid.
function ChipCard({
  label, chipKey, chip,
}: { label: string; chipKey: string; chip: DashQbChip | null }) {
  const pct = chip?.pct;
  const hue = pct != null ? Math.max(0, Math.min(120, pct * 1.2)) : 0;
  const fill = `hsl(${hue} 70% 50%)`;
  return (
    <div className="rounded-lg border border-border bg-bg-elevated/40 p-2">
      <div className="text-[10.5px] uppercase tracking-wider text-text-dim mb-0.5 truncate">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-text leading-none">
        {chip ? fmtChipValue(chipKey, chip.value) : '—'}
      </div>
      {pct != null ? (
        <div className="mt-1" title={`${pct}th percentile within the eligible QB pool`}>
          <div className="relative h-1 rounded-full bg-bg-elevated overflow-hidden">
            <div
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ width: `${pct}%`, backgroundColor: fill }}
            />
          </div>
          <div className={cn('mt-0.5 text-[10.5px] font-semibold tabular-nums')} style={{ color: fill }}>
            {pct}th
          </div>
        </div>
      ) : (
        <div className="mt-1 text-[10.5px] text-text-dim">—</div>
      )}
    </div>
  );
}
