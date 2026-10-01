import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { dashboardRoutes, type DashRoutes, type DashRouteSpoke } from '@/lib/dashboardApi';

// ---------------------------------------------------------------------------
// Radial route tree (Queue #8 viz 2). Receivers only (WR/TE/RB); hidden
// otherwise. 12 spokes around a hub. Spoke LENGTH = route mix % (volume), spoke
// COLOR = YPRR (efficiency); low-sample spokes (<8 routes) fade + dash so small
// samples don't dominate. Hover a spoke for routes/mix/targets/win%/YPRR.
// Dependency-free inline SVG. Sizes to fill its column (min of width/height) so
// it balances the tile grid; labels are padded so edge names aren't clipped.
// ---------------------------------------------------------------------------

const RECEIVERS = new Set(['WR', 'TE', 'RB']);
const SMALL_SAMPLE = 8;          // routes below this render faded/dashed
const YPRR_CLAMP = 4;            // color scale ceiling (routes basis)
const YPT_CLAMP = 14;            // color scale ceiling (targets basis: yards per target)

function colorFor(v: number | null, clamp = YPRR_CLAMP): string {
  if (v == null) return 'var(--tx-dim)';
  const c = Math.max(0, Math.min(clamp, v));
  const hue = (c / clamp) * 120; // red -> green
  return `hsl(${hue} 65% 54%)`;
}

// v2 (2026-10-01): two bases. 'routes' = routes run per route type (FTN, 2026-). 'targets' =
// 2016-2025 history, target share by the TARGETED receiver's route (nflverse): there is no
// routes-run denominator, so the wheel is labelled as targets and colored by yards per target.

export default function RouteTree({
  playerId,
  season,
  bucket,
}: {
  playerId: string;
  season: number;
  bucket: string | null;
}) {
  const [data, setData] = useState<DashRoutes | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const wrapRef = useRef<HTMLDivElement>(null);
  const tok = useRef(0);

  const isReceiver = !!bucket && RECEIVERS.has(bucket);

  useEffect(() => {
    if (!playerId || !isReceiver) { setData(null); return; }
    const t = ++tok.current;
    setLoading(true);
    setHover(null);
    dashboardRoutes(playerId, season)
      .then((d) => { if (t === tok.current) setData(d); })
      .catch(() => { if (t === tok.current) setData(null); })
      .finally(() => { if (t === tok.current) setLoading(false); });
  }, [playerId, season, isReceiver]);

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
  }, [isReceiver]);

  const spokes = data?.spokes ?? [];
  const isTargets = data?.basis === 'targets';
  const metric = (s: DashRouteSpoke) => (isTargets ? s.ypt ?? null : s.yprr);
  const clamp = isTargets ? YPT_CLAMP : YPRR_CLAMP;

  const layout = useMemo(() => {
    if (!dims.w || !dims.h || spokes.length === 0) return null;
    const size = Math.max(300, Math.min(dims.w, dims.h, 620));
    const cx = size / 2;
    const cy = size / 2;
    const pad = Math.max(74, Math.round(size * 0.16)); // room for edge labels
    const maxR = size / 2 - pad;
    const stub = maxR * 0.08;
    const hubR = Math.max(26, stub + 20);
    const maxMix = Math.max(1, ...spokes.map((s) => s.mix_pct));

    const nodes = spokes.map((s, i) => {
      const deg = -90 + i * (360 / spokes.length);
      const rad = (deg * Math.PI) / 180;
      const cos = Math.cos(rad);
      const sin = Math.sin(rad);
      // sqrt scale (not linear) so one dominant route type -- e.g. RBs, where
      // "Back" (checkdowns) routinely runs 70-80% of the mix -- doesn't crush
      // every other real route down to a length shorter than the hub disc's
      // radius. The hub is drawn LAST in SVG paint order (after every spoke),
      // so any spoke shorter than hubR is fully hidden underneath it -- which
      // is exactly what was happening: labels showed real percentages for
      // every route, but only the dominant one's line was long enough to
      // clear the hub and actually be visible. A floor of hubR+6 for any
      // nonzero-mix route guarantees its line is visible regardless of how
      // small its real share is; a route at a genuine 0% mix still correctly
      // gets no line at all.
      const ratio = maxMix > 0 ? s.mix_pct / maxMix : 0;
      const len = s.mix_pct > 0
        ? Math.max(hubR + 6, stub + Math.sqrt(ratio) * (maxR - stub))
        : stub;
      const tipX = cx + cos * len;
      const tipY = cy + sin * len;
      const labX = cx + cos * (maxR + 12);
      const labY = cy + sin * (maxR + 12);
      const small = (isTargets ? s.targets : s.routes) < SMALL_SAMPLE;
      const dotR = 3 + Math.min(s.targets, 30) / 30 * 4;
      return { s, i, cos, sin, tipX, tipY, labX, labY, len, small, dotR };
    });

    const rings = [0.25, 0.5, 0.75, 1].map((f) => stub + f * (maxR - stub));
    return { size, cx, cy, maxR, stub, hubR, nodes, rings };
  }, [dims, spokes, isTargets]);

  if (!isReceiver) return null;

  const hv = hover != null && layout ? layout.nodes[hover] : null;

  return (
    <div className="rounded-xl border border-border bg-bg-card p-4 w-full flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-1 shrink-0">
        <div className="text-[10px] uppercase tracking-wider text-text-muted">
          {isTargets ? 'Targets by route' : 'Route tree'} · {season}
          {data?.has_data
            ? isTargets
              ? ` · ${data.total_targets} tgt · ${data.weeks} wk`
              : ` · ${data.total_routes} routes · ${data.total_targets} tgt · ${data.weeks} wk`
            : ''}
        </div>
      </div>

      {/* legend leads, above the route wheel -- matches the IDP Alignment
          Profile's Role-bar-at-top layout, not buried below the diagram. */}
      {data?.has_data && (
        <div className="mb-2 text-xs text-text-muted text-center shrink-0">
          {isTargets
            ? <>length = target share · color = yards/target · faded = &lt;{SMALL_SAMPLE} targets</>
            : <>length = route share · color = YPRR · faded = &lt;{SMALL_SAMPLE} routes</>}
        </div>
      )}

      <div
        ref={wrapRef}
        className="relative w-full flex-1 min-h-0 flex flex-col items-center justify-center text-accent"
        onMouseLeave={() => setHover(null)}
      >
        {loading && !data ? (
          <div className="text-text-dim text-sm">Loading routes…</div>
        ) : !data?.has_data || !layout ? (
          <div className="text-text-dim/70 text-xs">No {season} route data.</div>
        ) : (
          <svg width={layout.size} height={layout.size} className="block">
            {/* concentric rings */}
            {layout.rings.map((r, i) => (
              <circle
                key={i}
                cx={layout.cx} cy={layout.cy} r={r}
                fill="none" stroke="rgb(255 255 255 / 0.07)"
              />
            ))}

            {/* spokes */}
            {layout.nodes.map((n) => (
              <g key={n.s.key} opacity={n.small ? 0.45 : 1}>
                <line
                  x1={layout.cx} y1={layout.cy} x2={n.tipX} y2={n.tipY}
                  stroke={colorFor(metric(n.s), clamp)}
                  strokeWidth={hover === n.i ? 4.5 : 2.75}
                  strokeDasharray={n.small ? '4 3' : undefined}
                  strokeLinecap="round"
                />
                <circle
                  cx={n.tipX} cy={n.tipY} r={n.dotR}
                  fill={colorFor(metric(n.s), clamp)} stroke="var(--bg)" strokeWidth={1}
                />
                {/* invisible fat hit-line for hover */}
                <line
                  x1={layout.cx} y1={layout.cy} x2={n.labX} y2={n.labY}
                  stroke="transparent" strokeWidth={20}
                  onMouseEnter={() => setHover(n.i)}
                  style={{ cursor: 'pointer' }}
                />
                {/* tip label (name + mix%) */}
                <text
                  x={n.labX} y={n.labY}
                  textAnchor={n.cos > 0.3 ? 'start' : n.cos < -0.3 ? 'end' : 'middle'}
                  dominantBaseline={n.sin > 0.3 ? 'hanging' : n.sin < -0.3 ? 'auto' : 'middle'}
                  fontSize={12.5}
                  fill={hover === n.i ? 'var(--tx)' : 'var(--tx)'}
                >
                  {n.s.label}
                  <tspan fill="var(--tx-mut)"> {Math.round(n.s.mix_pct)}%</tspan>
                </text>
              </g>
            ))}

            {/* hub — opaque disc masks the converging spokes so the total reads clearly */}
            <circle
              cx={layout.cx} cy={layout.cy} r={layout.hubR}
              fill="var(--bg)" stroke="rgb(255 255 255 / 0.18)"
            />
            <text
              x={layout.cx} y={layout.cy - 1} textAnchor="middle"
              fontSize={19} fontWeight={700} fill="var(--tx)"
            >
              {isTargets ? data.total_targets : data.total_routes}
            </text>
            <text
              x={layout.cx} y={layout.cy + 13} textAnchor="middle"
              fontSize={10.5} fill="var(--tx-mut)"
              style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}
            >
              {isTargets ? 'targets' : 'routes'}
            </text>
          </svg>
        )}

        {hv && (
          <div
            className="pointer-events-none absolute z-10 rounded-md border border-border
                       bg-bg-card px-2.5 py-1.5 text-xs shadow-xl shadow-black/50"
            style={{
              left: Math.min(Math.max(hv.tipX - 60, 0), Math.max(0, (layout?.size ?? 0) - 140)),
              top: Math.max(0, hv.tipY - 4),
            }}
          >
            <div className="text-text font-semibold">{hv.s.label}</div>
            {isTargets ? (
              <>
                <div className="text-text-muted tabular-nums">
                  {Math.round(hv.s.targets)} tgt · {Math.round(hv.s.mix_pct)}% of targets
                </div>
                <div className="text-text-dim tabular-nums">
                  {hv.s.receptions ?? 0} rec · {hv.s.ypt != null ? `${hv.s.ypt} yds/tgt` : 'yds/tgt —'}
                </div>
              </>
            ) : (
              <>
                <div className="text-text-muted tabular-nums">
                  {hv.s.routes} routes · {Math.round(hv.s.mix_pct)}% mix
                </div>
                <div className="text-text-dim tabular-nums">
                  {Math.round(hv.s.targets)} tgt
                  {hv.s.win_rate != null ? ` · ${Math.round(hv.s.win_rate)}% win` : ''}
                </div>
                <div className="text-text-dim tabular-nums">
                  {hv.s.yprr != null ? `${hv.s.yprr} YPRR` : 'YPRR —'}
                  {hv.s.ador != null ? ` · ${hv.s.ador} ADOR` : ''}
                </div>
              </>
            )}
            {hv.small && <div className="text-warn">small sample (&lt;{SMALL_SAMPLE})</div>}
          </div>
        )}
      </div>
    </div>
  );
}

export type { DashRouteSpoke };
