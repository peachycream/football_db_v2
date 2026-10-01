import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { dashboardTrinity, type DashTrinity } from '@/lib/dashboardApi';

// ---------------------------------------------------------------------------
// Trinity Score panel (WR / TE / RB). Dots = each week's score on its own
// (against that week's WR/TE pool); the solid line = season to date (weeks 1..N
// together), which is the number DD's page shows for a full season. Shaded
// bands are DD's tier thresholds for the position (RB use the WR bands).
//
// The score is DD Fantasy Football's formula, ported (fdb/trinity.py), so it is
// a derived number. DD's own PUBLISHED season score is shown beside it and can
// differ for some players. Weeks where DD's data is wrong at the source are
// never loaded; they are hatched here and named, never plotted as zero.
//
// Dependency-free inline SVG, same approach as SnapTrend.
// ---------------------------------------------------------------------------

const H = 230;
const M = { t: 14, r: 64, b: 22, l: 26 };

const TIER_COLOR: Record<string, string> = {
  'Elite': '#FACC15',
  'Above League Average': '#34D399',
  'League Average': '#60A5FA',
  'Below League Average': '#FB923C',
  'Depth': '#94A3B8',
};
const tierColor = (t: string | null | undefined) => (t && TIER_COLOR[t]) || '#94A3B8';
const tierShort = (t: string | null | undefined) =>
  t === 'Above League Average' ? 'Above Avg'
    : t === 'League Average' ? 'Average'
      : t === 'Below League Average' ? 'Below Avg'
        : t ?? '';

function weekList(weeks: number[]): string {
  const w = [...weeks].sort((a, b) => a - b);
  if (w.length === 0) return '';
  const runs: string[] = [];
  let a = w[0], b = w[0];
  for (let i = 1; i <= w.length; i++) {
    if (i < w.length && w[i] === b + 1) { b = w[i]; continue; }
    runs.push(a === b ? `${a}` : `${a}–${b}`);
    if (i < w.length) { a = w[i]; b = w[i]; }
  }
  return runs.join(', ');
}

export default function TrinityTrend({
  playerId,
  season,
  bucket,
}: {
  playerId: string;
  season: number;
  bucket: string | null;
}) {
  const supported = bucket === 'WR' || bucket === 'TE' || bucket === 'RB';
  const [data, setData] = useState<DashTrinity | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [w, setW] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const tok = useRef(0);

  useEffect(() => {
    if (!playerId || !supported) { setData(null); return; }
    const t = ++tok.current;
    setLoading(true);
    setHover(null);
    dashboardTrinity(playerId, season)
      .then((d) => { if (t === tok.current) setData(d); })
      .catch(() => { if (t === tok.current) setData(null); })
      .finally(() => { if (t === tok.current) setLoading(false); });
  }, [playerId, season, supported]);

  // The chart div only mounts once there is data to draw, so measure when that changes.
  const drawable = !!data && data.has_data;
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(Math.floor(e.contentRect.width));
    });
    ro.observe(el);
    setW(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, [drawable, supported]);

  const layout = useMemo(() => {
    if (!data || !w || !data.has_data) return null;
    const innerW = Math.max(0, w - M.l - M.r);
    const innerH = H - M.t - M.b;
    const allWeeks = [
      ...data.weekly.map((p) => p.week),
      ...data.through.map((p) => p.week),
      ...data.withheld_weeks,
    ];
    const maxWeek = Math.max(1, ...allWeeks);
    const x = (week: number) => M.l + (maxWeek === 1 ? innerW / 2 : ((week - 1) / (maxWeek - 1)) * innerW);
    const y = (s: number) => M.t + innerH - (Math.max(0, Math.min(10, s)) / 10) * innerH;
    const colW = maxWeek === 1 ? innerW : innerW / (maxWeek - 1);

    // tier bands: [min, next-higher min) coloured by the tier that starts at min
    const bands = data.bands.map((b, i) => {
      const hi = i === 0 ? 10 : data.bands[i - 1].min;
      return { ...b, y0: y(hi), y1: y(b.min), color: tierColor(b.label) };
    });
    const last = data.bands[data.bands.length - 1];
    const depth = { label: 'Depth', y0: y(last ? last.min : 0), y1: y(0), color: tierColor('Depth') };

    const weekly = data.weekly.map((p) => ({ ...p, px: x(p.week), py: y(p.score) }));
    const through = data.through.map((p) => ({ ...p, px: x(p.week), py: y(p.score) }));
    // break the line at a withheld week rather than drawing across it
    const withheld = new Set(data.withheld_weeks);
    let path = '';
    through.forEach((n, i) => {
      const prev = through[i - 1];
      const gap = !prev || [...withheld].some((wk) => wk > prev.week && wk < n.week);
      path += `${gap ? 'M' : 'L'}${n.px.toFixed(1)},${n.py.toFixed(1)} `;
    });
    const ticks = [0, 2.5, 5, 7.5, 10].map((v) => ({ v, py: y(v) }));
    const hatch = data.withheld_weeks.map((wk) => ({ wk, px: x(wk) }));
    const xs = Array.from({ length: maxWeek }, (_, i) => i + 1).map((wk) => ({ wk, px: x(wk) }));
    return { innerW, innerH, maxWeek, x, y, colW, bands, depth, weekly, through, path: path.trim(), ticks, hatch, xs };
  }, [w, data]);

  if (!supported) return null;

  // hover -> nearest WEEK (weeks are what the reader scans), then show that week's numbers
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!layout) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const scaleX = rect.width ? w / rect.width : 1; // correct for CSS zoom
    const mx = (e.clientX - rect.left) * scaleX;
    const wk = Math.max(1, Math.min(layout.maxWeek, Math.round(1 + ((mx - M.l) / Math.max(1, layout.innerW)) * (layout.maxWeek - 1))));
    setHover((prev) => (prev === wk ? prev : wk));
  };

  const hw = hover != null && layout ? layout.weekly.find((p) => p.week === hover) ?? null : null;
  const ht = hover != null && layout ? layout.through.find((p) => p.week === hover) ?? null : null;
  const hOut = hover != null && data ? data.withheld_weeks.includes(hover) : false;
  const s = data?.summary ?? null;

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 mb-2">
      <div className="text-[10px] uppercase tracking-wider text-text-muted pt-1">
        Trinity Score · by week
      </div>
      {s && (
        <div className="flex items-center gap-4 text-right">
          <div>
            <div className="flex items-baseline justify-end gap-1.5">
              <span className="text-2xl font-semibold tabular-nums leading-none" style={{ color: tierColor(s.tier) }}>
                {s.score.toFixed(2)}
              </span>
              <span className="text-[11px] font-semibold" style={{ color: tierColor(s.tier) }}>{tierShort(s.tier)}</span>
            </div>
            <div className="text-[10px] text-text-dim tabular-nums">
              {s.position}{s.rank}{s.pool ? ` of ${s.pool}` : ''} · season to date, thru wk {s.week}
            </div>
          </div>
          {data?.stored && (
            <div
              title="DD Fantasy Football's own published season score. It is built by DD (by player name) and is a different computation from the ported formula for some players, so it can differ from the number at left."
              className="border-l border-border pl-4"
            >
              <div className="text-sm font-semibold tabular-nums text-text leading-none">
                {data.stored.score.toFixed(2)}
              </div>
              <div className="text-[10px] text-text-dim">DD season score{data.stored.rank ? ` · #${data.stored.rank}` : ''}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );

  return (
    <div className="rounded-xl border border-border bg-bg-card p-4 w-full">
      {header}

      <div ref={wrapRef} className="relative w-full text-accent">
        {loading && !data ? (
          <div className="flex items-center justify-center text-text-dim text-sm" style={{ height: H }}>
            Loading Trinity…
          </div>
        ) : data && season < data.first_season ? (
          <div className="flex items-center justify-center text-text-dim/70 text-xs" style={{ height: 90 }}>
            Trinity data starts in {data.first_season}.
          </div>
        ) : !data || !data.has_data ? (
          <div className="flex items-center justify-center text-text-dim/70 text-xs text-center px-6" style={{ height: 90 }}>
            No Trinity score for {season}: DD only scores receivers above a small target floor.
          </div>
        ) : layout ? (
          <>
            <svg width={w} height={H} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="block">
              <defs>
                <pattern id="trin-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <line x1="0" y1="0" x2="0" y2="6" stroke="rgb(255 255 255 / 0.18)" strokeWidth="2" />
                </pattern>
              </defs>

              {/* tier bands */}
              {[...layout.bands, layout.depth].map((b) => (
                <g key={b.label}>
                  <rect x={M.l} width={layout.innerW} y={b.y0} height={Math.max(0, b.y1 - b.y0)}
                        fill={b.color} opacity={0.07} />
                  <text x={w - M.r + 6} y={(b.y0 + b.y1) / 2 + 3} fontSize={9} fill={b.color}>
                    {tierShort(b.label)}
                  </text>
                </g>
              ))}

              {/* y gridlines + labels */}
              {layout.ticks.map((t) => (
                <g key={t.v}>
                  <line x1={M.l} x2={M.l + layout.innerW} y1={t.py} y2={t.py}
                        stroke="rgb(255 255 255 / 0.06)" strokeDasharray="3 3" />
                  <text x={M.l - 6} y={t.py + 3} textAnchor="end" fontSize={10} fill="var(--tx-mut)">{t.v}</text>
                </g>
              ))}

              {/* withheld weeks: hatched, never plotted */}
              {layout.hatch.map((h) => (
                <rect key={`wh-${h.wk}`} x={h.px - layout.colW / 2} width={layout.colW}
                      y={M.t} height={layout.innerH} fill="url(#trin-hatch)" />
              ))}

              {/* x labels */}
              {layout.xs.map((n) => (
                <text key={`xl-${n.wk}`} x={n.px} y={H - 6} textAnchor="middle" fontSize={10}
                      fill={data.withheld_weeks.includes(n.wk) ? 'var(--mid)' : 'var(--tx-mut)'}>
                  {n.wk}
                </text>
              ))}

              {hover != null && (
                <line x1={layout.x(hover)} x2={layout.x(hover)} y1={M.t} y2={H - M.b} stroke="rgb(255 255 255 / 0.18)" />
              )}

              {/* season to date */}
              <path d={layout.path} fill="none" stroke="currentColor" strokeWidth={2} opacity={0.9} />

              {/* each week on its own */}
              {layout.weekly.map((n) => (
                <circle key={`pt-${n.week}`} cx={n.px} cy={n.py} r={hover === n.week ? 5 : 3.5}
                        fill={tierColor(n.tier)} stroke="var(--bg)" strokeWidth={1} />
              ))}
            </svg>

            {hover != null && (hw || ht || hOut) && (
              <div
                className="pointer-events-none absolute z-10 rounded-md border border-border bg-bg-card
                           px-2.5 py-1.5 text-xs shadow-xl shadow-black/50"
                style={{ left: Math.min(Math.max(layout.x(hover) - 60, 0), Math.max(0, w - 190)), top: 4 }}
              >
                <div className="text-text font-semibold">Week {hover}{hw ? ` · ${hw.team}` : ''}</div>
                {hOut && <div className="text-warn">DD data withheld (wrong at the source)</div>}
                {hw && (
                  <>
                    <div className="tabular-nums" style={{ color: tierColor(hw.tier) }}>
                      {hw.score.toFixed(2)} · {tierShort(hw.tier)} · {hw.position}{hw.rank} that week
                    </div>
                    <div className="text-text-muted tabular-nums">
                      {hw.targets} tgt · {hw.rec} rec · {hw.rec_yards} yds{hw.rec_td ? ` · ${hw.rec_td} TD` : ''}
                    </div>
                  </>
                )}
                {!hw && !hOut && <div className="text-text-dim">no Trinity score this week (bye, out, or under DD's target floor)</div>}
                {ht && (
                  <div className="text-text-dim tabular-nums mt-0.5">
                    season to date {ht.score.toFixed(2)} ({tierShort(ht.tier)}, {ht.position}{ht.rank})
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          <div style={{ height: H }} />
        )}
      </div>

      {data && data.has_data && (
        <div className="mt-2 flex items-center gap-4 text-[10px] text-text-dim">
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-full bg-text-dim" /> week alone</span>
          <span className="flex items-center gap-1"><span className="inline-block w-4 h-0.5 bg-accent" /> season to date</span>
        </div>
      )}
      {data && data.withheld_weeks.length > 0 && (
        <div className="mt-1 text-[10px] text-warn">
          ⚠ Week{data.withheld_weeks.length > 1 ? 's' : ''} {weekList(data.withheld_weeks)} not shown: DD's data for{' '}
          {data.withheld_weeks.length > 1 ? 'them is' : 'it is'} wrong at the source (never loaded), so the season-to-date line
          stops where it would cross {data.withheld_weeks.length > 1 ? 'them' : 'it'}.
        </div>
      )}
    </div>
  );
}
