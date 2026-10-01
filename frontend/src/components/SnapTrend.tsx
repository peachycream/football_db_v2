import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { dashboardSnaps, type DashSnaps, type DashSnapPoint } from '@/lib/dashboardApi';

// ---------------------------------------------------------------------------
// Snap-trend line (Queue #8 viz 1). X = week, Y = total snaps, point label =
// snap %. Offense buckets plot offensive snaps; defense plot defensive (the
// backend picks the side from the player's bucket). Weeks carrying snaps under
// this slug from more than one team are flagged (same-slug collision marker) —
// amber dot + header note, surfaced not silently merged. Renders for every
// bucket; hidden only when there is no data.
//
// Dependency-free inline SVG (no chart lib): the bundle is already large and
// viz 2's radial tree is hand-rolled SVG too, so the viz layer stays consistent.
// ---------------------------------------------------------------------------

const H = 210;                              // svg height (px)
const M = { t: 24, r: 16, b: 22, l: 30 };   // margins

export default function SnapTrend({
  playerId,
  season,
  side,
}: {
  playerId: string;
  season: number;
  side: 'offense' | 'defense' | null;
}) {
  const [data, setData] = useState<DashSnaps | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [w, setW] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const tok = useRef(0);

  // fetch
  useEffect(() => {
    if (!playerId) { setData(null); return; }
    const t = ++tok.current;
    setLoading(true);
    setHover(null);
    dashboardSnaps(playerId, season)
      .then((d) => { if (t === tok.current) setData(d); })
      .catch(() => { if (t === tok.current) setData(null); })
      .finally(() => { if (t === tok.current) setLoading(false); });
  }, [playerId, season]);

  // measure width. Depends on `side`, not []: the component returns null
  // (line ~90) whenever side is neither 'offense' nor 'defense', which means
  // wrapRef's div never mounts on that render — for a deep-linked player,
  // side starts null and only resolves after the header loads, so an
  // empty-deps effect would attach to nothing and never retry once the div
  // actually appears. Matches the [isReceiver]/[isRb]/[isQb] pattern already
  // used by RouteTree/RbRushingProfile/QbPassingProfile for the same reason.
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(Math.floor(e.contentRect.width));
    });
    ro.observe(el);
    setW(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, [side]);

  const pts = data?.points ?? [];
  const label =
    data?.side_label ?? (side === 'defense' ? 'Defensive snaps' : 'Offensive snaps');

  const layout = useMemo(() => {
    if (!w || pts.length === 0) return null;
    const innerW = Math.max(0, w - M.l - M.r);
    const innerH = H - M.t - M.b;

    const weeks = pts.map((p) => p.week);
    const minW = Math.min(...weeks);
    const maxW = Math.max(...weeks);
    const span = Math.max(1, maxW - minW);
    const maxSnaps = Math.max(1, ...pts.map((p) => p.snaps));
    const niceMax = Math.ceil(maxSnaps / 10) * 10 || 10;

    const x = (week: number) =>
      M.l + (pts.length === 1 ? innerW / 2 : ((week - minW) / span) * innerW);
    const y = (snaps: number) => M.t + innerH - (snaps / niceMax) * innerH;

    const nodes = pts.map((p) => ({ ...p, px: x(p.week), py: y(p.snaps) }));
    const path = nodes
      .map((n, i) => `${i ? 'L' : 'M'}${n.px.toFixed(1)},${n.py.toFixed(1)}`)
      .join(' ');
    const yTicks = [0, 0.5, 1].map((f) => {
      const v = Math.round(niceMax * f);
      return { v, py: y(v) };
    });
    return { innerW, innerH, minW, maxW, niceMax, x, y, nodes, path, yTicks };
  }, [w, pts]);

  if (side !== 'offense' && side !== 'defense') return null;

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!layout) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const scaleX = rect.width ? w / rect.width : 1; // correct for CSS zoom
    const mx = (e.clientX - rect.left) * scaleX;
    let best = 0;
    let bestD = Infinity;
    layout.nodes.forEach((n, i) => {
      const d = Math.abs(n.px - mx);
      if (d < bestD) { bestD = d; best = i; }
    });
    // hysteresis: right at the midpoint between two adjacent points, sub-pixel
    // jitter in mx can flip "best" back and forth on every mousemove, which
    // reads as the tooltip flickering/shaking between two weeks. Only switch
    // away from the currently-hovered point once the new one is meaningfully
    // closer, not just marginally.
    setHover((prev) => {
      if (prev != null && prev !== best) {
        const prevD = Math.abs(layout.nodes[prev].px - mx);
        if (prevD - bestD < 4) return prev;
      }
      return best;
    });
  };

  const hv = hover != null && layout ? layout.nodes[hover] : null;

  return (
    <div className="rounded-xl border border-border bg-bg-card p-4 w-full">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] uppercase tracking-wider text-text-muted">
          {label} · by week
          {data?.season_high ? ` · high ${data.season_high}` : ''}
        </div>
        {!!data?.collision_weeks && (
          <span
            title="One or more weeks carry snaps under this slug from more than one team — likely a same-name slug collision (Y4.6 audit). Shown, not merged silently."
            className="text-warn text-[10px]"
          >
            ⚠ {data.collision_weeks} multi-team wk
          </span>
        )}
      </div>

      <div ref={wrapRef} className="relative w-full text-accent">
        {loading && !data ? (
          <div className="flex items-center justify-center text-text-dim text-sm" style={{ height: H }}>
            Loading snaps…
          </div>
        ) : pts.length === 0 ? (
          <div className="flex items-center justify-center text-text-dim/70 text-xs" style={{ height: H }}>
            No snap data for {season}.
          </div>
        ) : layout ? (
          <>
            <svg
              width={w}
              height={H}
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
              className="block"
            >
              {/* y gridlines + labels */}
              {layout.yTicks.map((t) => (
                <g key={t.v}>
                  <line
                    x1={M.l} x2={w - M.r} y1={t.py} y2={t.py}
                    stroke="rgb(255 255 255 / 0.06)" strokeDasharray="3 3"
                  />
                  <text
                    x={M.l - 6} y={t.py + 3} textAnchor="end"
                    fontSize={10} fill="var(--tx-mut)"
                  >
                    {t.v}
                  </text>
                </g>
              ))}

              {/* x labels (week numbers) */}
              {layout.nodes.map((n) => (
                <text
                  key={`xl-${n.week}`}
                  x={n.px} y={H - 6} textAnchor="middle"
                  fontSize={10} fill="var(--tx-mut)"
                >
                  {n.week}
                </text>
              ))}

              {/* hover guide */}
              {hv && (
                <line
                  x1={hv.px} x2={hv.px} y1={M.t} y2={H - M.b}
                  stroke="rgb(255 255 255 / 0.15)"
                />
              )}

              {/* line */}
              <path d={layout.path} fill="none" stroke="currentColor" strokeWidth={2} />

              {/* points + snap% labels */}
              {layout.nodes.map((n, i) => (
                <g key={`pt-${n.week}`}>
                  <text
                    x={n.px} y={n.py - 8} textAnchor="middle"
                    fontSize={9} fill="var(--tx)"
                  >
                    {Math.round(n.snap_pct)}%
                  </text>
                  <circle
                    cx={n.px} cy={n.py}
                    r={n.multi_team ? 4 : 3}
                    fill={n.multi_team ? 'var(--mid)' : 'currentColor'}
                    stroke="var(--bg)" strokeWidth={1}
                    opacity={hover == null || hover === i ? 1 : 0.6}
                  />
                </g>
              ))}
            </svg>

            {hv && (
              <div
                className="pointer-events-none absolute z-10 rounded-md border border-border
                           bg-bg-card px-2.5 py-1.5 text-xs shadow-xl shadow-black/50"
                style={{
                  left: Math.min(Math.max(hv.px - 40, 0), Math.max(0, w - 120)),
                  // pinned near the top of the chart, NOT tracking hv.py (the
                  // hovered point's own y-position) -- week-to-week snap%
                  // swings mean that would make the tooltip box jump up and
                  // down as you sweep across weeks, reading as an unstable
                  // "shaking" tooltip and making it hard to track values.
                  top: 4,
                }}
              >
                <div className="text-text font-semibold">Week {hv.week}</div>
                <div className="text-text-muted tabular-nums">
                  {hv.snaps} snaps · {Math.round(hv.snap_pct)}%
                </div>
                {hv.team && <div className="text-text-dim">{hv.team}</div>}
                {hv.multi_team && <div className="text-warn">⚠ multi-team week</div>}
              </div>
            )}
          </>
        ) : (
          <div style={{ height: H }} />
        )}
      </div>
    </div>
  );
}

// keep the point type exported for any type-only consumers
export type { DashSnapPoint };
