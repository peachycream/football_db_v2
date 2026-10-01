import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  dashboardRbLanes,
  type DashRbLanes,
  type DashRbLane,
  type DashRbChip,
} from '@/lib/dashboardApi';

// ---------------------------------------------------------------------------
// RB Rushing Profile (Player Profile Sections Phase 2, P2.1/P2.6). RB-only.
// Same "primary vertical visual" slot as QbPassingProfile/RouteTree --
// mutually exclusive by bucket, same responsive ResizeObserver pattern
// (wrapRef div always rendered, per the bug fixed in QbPassingProfile).
//
// Run-lane strip: horizontal O-line graphic, 7 lanes (LE/LT/LG/M/RG/RT/RE)
// left to right. Lane fill = diverging scale on lane EPA/att MINUS the
// league-average EPA/att for that lane, clamped ±0.15, green hot / red cold.
// Carry-share label inline; low-sample lanes (<8 carries) desaturated.
// ---------------------------------------------------------------------------

const LOW_SAMPLE = 8;
const EPA_DELTA_CLAMP = 0.15;
const LANES: DashRbLane['lane'][] = ['LE', 'LT', 'LG', 'M', 'RG', 'RT', 'RE'];
const LINE_MARKER: Record<DashRbLane['lane'], string> = {
  LE: '', LT: 'T', LG: 'G', M: 'C', RG: 'G', RT: 'T', RE: '',
};

function laneColor(delta: number | null, lowSample: boolean): string {
  if (lowSample || delta == null) return 'var(--surf-3)';
  const c = Math.max(-EPA_DELTA_CLAMP, Math.min(EPA_DELTA_CLAMP, delta));
  const t = Math.abs(c) / EPA_DELTA_CLAMP;
  const hue = c >= 0 ? 120 : 0;
  const sat = Math.round(15 + t * 65);
  const light = Math.round(14 + t * 26);
  return `hsl(${hue} ${sat}% ${light}%)`;
}

const CHIP_LABELS: { key: keyof NonNullable<DashRbLanes['header']>; label: string }[] = [
  { key: 'mtf_per_att', label: 'MTF/Att' },
  { key: 'yac_per_att', label: 'YAC/Att' },
  { key: 'explosive_rate', label: 'Explosive%' },
  { key: 'breakaway_pct', label: 'Breakaway%' },
  { key: 'success_rate', label: 'Success Rate' },
];

function fmtChipValue(key: string, v: number): string {
  if (key === 'explosive_rate' || key === 'breakaway_pct' || key === 'success_rate') {
    return `${(v * 100).toFixed(0)}%`;
  }
  return v.toFixed(2);
}

export default function RbRushingProfile({
  playerId,
  season,
  bucket,
}: {
  playerId: string;
  season: number;
  bucket: string | null;
}) {
  const [data, setData] = useState<DashRbLanes | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const wrapRef = useRef<HTMLDivElement>(null);

  const isRb = bucket === 'RB';

  useEffect(() => {
    if (!playerId || !isRb) { setData(null); return; }
    let cancelled = false;
    setLoading(true);
    setHover(null);
    dashboardRbLanes(playerId, season)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [playerId, season, isRb]);

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
  }, [isRb]);

  const laneMap = useMemo(
    () => new Map((data?.lanes ?? []).map((l) => [l.lane, l])),
    [data],
  );
  const hovered = hover ? laneMap.get(hover as DashRbLane['lane']) : null;

  // grid geometry: single horizontal row of 7 lanes, capped height so it
  // reads as a band rather than sprawling on tall narrow screens
  const layout = useMemo(() => {
    if (!dims.w || !dims.h) return null;
    const markerRowH = 16;
    const laneW = dims.w / LANES.length;
    const laneH = Math.max(70, Math.min(dims.h - markerRowH - 30, 160));
    return { laneW, laneH, markerRowH };
  }, [dims]);

  if (!isRb) return null;

  return (
    <div className="rounded-xl border border-border bg-bg-card p-4 w-full flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="text-[10px] uppercase tracking-wider text-text-muted">
          Rushing Profile · {season}
          {data?.eligible && data.carries != null ? ` · ${data.carries} carries` : ''}
        </div>
      </div>

      {/* percentile chip strip — only once real eligible data exists */}
      {data?.eligible && (
        <div className="grid grid-cols-5 gap-2 mb-3 shrink-0">
          {CHIP_LABELS.map(({ key, label }) => {
            const chip = data.header?.[key] as DashRbChip | null | undefined;
            return <ChipCard key={key} label={label} chipKey={key} chip={chip ?? null} />;
          })}
        </div>
      )}

      {/* legend leads, above the lane strip -- matches the IDP Alignment
          Profile's Role-bar-at-top layout, not buried below the diagram. */}
      {data?.eligible && (
        <div className="mb-2 text-xs text-text-muted text-center shrink-0">
          fill = EPA/att vs league-average for that lane (green hot / red cold, ±{EPA_DELTA_CLAMP}) · label = carry share
        </div>
      )}

      {/* lane strip wrapper — ALWAYS rendered (unconditionally), matching
          QbPassingProfile/RouteTree's ResizeObserver pattern so the observer
          has a real DOM node to attach to on mount, before `data` loads. */}
      <div
        ref={wrapRef}
        className="relative w-full flex-1 min-h-0 flex flex-col items-center justify-center"
      >
        {loading && !data ? (
          <div className="text-text-dim text-sm">Loading rushing profile…</div>
        ) : !data?.eligible ? (
          <div className="text-text-dim/70 text-xs text-center px-4">
            {data?.reason ?? `No ${season} rushing profile data.`}
          </div>
        ) : (
          <>
            {layout && (
              <svg width={dims.w} height={layout.laneH + layout.markerRowH} className="block">
                {LANES.map((lane, i) => {
                  const x = i * layout.laneW;
                  return (
                    <text
                      key={`marker-${lane}`}
                      x={x + layout.laneW / 2} y={layout.markerRowH - 4}
                      textAnchor="middle" fontSize={11.5} fill="var(--tx-mut)"
                    >
                      {LINE_MARKER[lane]}
                    </text>
                  );
                })}

                {LANES.map((lane, i) => {
                  const x = i * layout.laneW;
                  const y = layout.markerRowH;
                  const l = laneMap.get(lane);
                  const carries = l?.carries ?? 0;
                  const low = carries < LOW_SAMPLE;
                  const delta = l?.epa_per_att != null && l?.lg_avg_epa_per_att != null
                    ? l.epa_per_att - l.lg_avg_epa_per_att : null;
                  const fill = laneColor(delta, low);
                  const isHovered = hover === lane;
                  return (
                    <g key={lane}>
                      <rect
                        x={x + 2} y={y} width={layout.laneW - 4} height={layout.laneH}
                        fill={fill}
                        stroke={isHovered ? 'var(--accent)' : 'rgb(255 255 255 / 0.08)'}
                        strokeWidth={isHovered ? 2 : 1}
                        opacity={low ? 0.55 : 1}
                        rx={4}
                        style={{ cursor: 'pointer' }}
                        onMouseEnter={() => setHover(lane)}
                        onMouseLeave={() => setHover(null)}
                      />
                      <text
                        x={x + layout.laneW / 2} y={y + layout.laneH / 2 - 6}
                        textAnchor="middle" fontSize={13} fontWeight={700}
                        fill="var(--tx)" pointerEvents="none"
                      >
                        {lane}
                      </text>
                      <text
                        x={x + layout.laneW / 2} y={y + layout.laneH / 2 + 12}
                        textAnchor="middle" fontSize={14} fontWeight={600}
                        fill="var(--tx)" pointerEvents="none"
                      >
                        {carries > 0 ? `${Math.round((l?.carry_share ?? 0) * 100)}%` : '—'}
                      </text>
                    </g>
                  );
                })}
              </svg>
            )}

            {hovered && (
              <div
                className="pointer-events-none absolute z-10 rounded-md border border-border
                           bg-bg-card px-2.5 py-1.5 text-xs shadow-xl shadow-black/50"
                style={{ left: 12, bottom: 12 }}
              >
                <div className="text-text font-semibold">{hover} lane</div>
                <div className="text-text-muted tabular-nums mt-0.5">
                  {hovered.carries} carries · {hovered.carries >= LOW_SAMPLE
                    ? `${(hovered.ypc ?? 0).toFixed(1)} YPC`
                    : 'YPC —'}
                </div>
                <div className="text-text-dim tabular-nums">
                  {hovered.carries >= LOW_SAMPLE && hovered.success_rate != null
                    ? `${(hovered.success_rate * 100).toFixed(0)}% success` : 'success —'}
                  {hovered.epa_per_att != null && hovered.carries >= LOW_SAMPLE
                    ? ` · ${hovered.epa_per_att.toFixed(2)} EPA/att` : ''}
                </div>
                {hovered.lg_avg_epa_per_att != null && hovered.carries >= LOW_SAMPLE && (
                  <div className="text-text-dim tabular-nums">
                    lg avg {hovered.lg_avg_epa_per_att.toFixed(2)} EPA/att
                  </div>
                )}
                {hovered.carries < LOW_SAMPLE && (
                  <div className="text-warn mt-0.5">small sample (&lt;{LOW_SAMPLE} carries)</div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// Same percentile-fill-bar convention as QbPassingProfile's ChipCard.
function ChipCard({
  label, chipKey, chip,
}: { label: string; chipKey: string; chip: DashRbChip | null }) {
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
        <div className="mt-1" title={`${pct}th percentile within the eligible RB pool`}>
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
