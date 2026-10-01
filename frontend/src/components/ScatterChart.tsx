import { useMemo } from 'react';
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - no types shipped for the factory entry
import createPlotlyComponentRaw from 'react-plotly.js/factory';
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - no types shipped for plotly.js-dist-min
import Plotly from 'plotly.js-dist-min';
import type { QueryResponse, Dot, StatMeta } from '@/types/api';
import type { Highlight, TrendlineMode } from '@/state/queryState';
import { token } from '@/lib/tokens';
import { teamColor, MARKER_STROKE } from '@/lib/teamColors';
import { LABEL_CAP } from '@/lib/constants';
import { formatStat } from '@/lib/utils';

// Factory pattern — works around an ESM/CJS interop issue between
// react-plotly.js and Vite that causes "Element type is invalid" errors.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const createPlotlyComponent: any =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (createPlotlyComponentRaw as any).default ?? createPlotlyComponentRaw;
const Plot = createPlotlyComponent(Plotly);

interface ScatterChartProps {
  data: QueryResponse;
  showQuadrants: boolean;
  showLabels: boolean;
  highlights: Highlight[];
  trendline: TrendlineMode;
}

const SIZE_MIN = 6;
const SIZE_MAX = 22;
const DEFAULT_SIZE = 9;

// Name labels on the base dots. Subordinate to the accent-green highlight
// labels so a highlighted player still reads first.
// Resolved lazily: Plotly needs a real colour string, and the token is read
// from theme.css at call time so a per-tool accent is picked up correctly.
const labelFont = () => ({ color: token('tx-mut'), size: 10, family: 'Inter, sans-serif' });

export function ScatterChart({
  data, showQuadrants, showLabels, highlights, trendline,
}: ScatterChartProps) {
  const { dots, x_meta, y_meta, color_meta, size_meta } = data;
  const highlightIds = useMemo(
    () => new Set(highlights.map(h => h.player_id)),
    [highlights],
  );

  // Memoize derived data
  const chartData = useMemo(() => {
    const xs = dots
      .map((d: Dot) => d.x)
      .filter((v): v is number => v != null);
    const ys = dots
      .map((d: Dot) => d.y)
      .filter((v): v is number => v != null);
    const medianX = xs.length ? median(xs) : null;
    const medianY = ys.length ? median(ys) : null;

    const xMin = xs.length ? Math.min(...xs) : 0;
    const xMax = xs.length ? Math.max(...xs) : 1;
    const yMin = ys.length ? Math.min(...ys) : 0;
    const yMax = ys.length ? Math.max(...ys) : 1;
    const xPad = (xMax - xMin) * 0.05 || 0.1;
    const yPad = (yMax - yMin) * 0.05 || 0.1;

    // Size-encode bounds
    let sizeRange: { min: number; max: number } | null = null;
    if (size_meta) {
      const sizes = dots.map(d => d.size).filter((v): v is number => v != null);
      if (sizes.length) {
        sizeRange = { min: Math.min(...sizes), max: Math.max(...sizes) };
      }
    }

    return { medianX, medianY, xMin, xMax, yMin, yMax, xPad, yPad, sizeRange };
  }, [dots, size_meta]);

  const isCategoricalColor = color_meta?.value_type === 'categorical';
  const isTeamColor = color_meta?.stat_id === 'a_team';

  // Plotly does no label decluttering — every label renders, overlaps and all.
  // Past LABEL_CAP the names become an unreadable smear, so the toggle
  // self-suppresses rather than ruining the chart. Sidebar shows why.
  const labelsOn = showLabels && dots.length <= LABEL_CAP;

  // Linear size scale from size_meta values to marker pixel size
  const markerSize = (d: Dot): number => {
    if (!chartData.sizeRange || d.size == null) return DEFAULT_SIZE;
    const { min, max } = chartData.sizeRange;
    if (max === min) return DEFAULT_SIZE;
    const t = (d.size - min) / (max - min);
    return SIZE_MIN + t * (SIZE_MAX - SIZE_MIN);
  };

  // Build traces. Highlights go on their own trace on top with outline+label.
  // Non-highlighted dots are dimmed when any highlight exists, to draw focus.
  const traces = useMemo(() => {
    const hasHighlights = highlights.length > 0;
    const baseOpacity = hasHighlights ? 0.35 : 0.85;
    const nonHighlighted = dots.filter(d => !highlightIds.has(d.player_id));
    const highlighted = dots.filter(d => highlightIds.has(d.player_id));

    // ----- base trace(s) -----
    let baseTraces: any[] = [];

    if (isCategoricalColor) {
      // Group dots by color value — one trace per category for legend.
      const groups = new Map<string, Dot[]>();
      for (const d of nonHighlighted) {
        const key = d.color == null ? 'Unknown' : String(d.color);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key)!.push(d);
      }
      baseTraces = Array.from(groups.entries()).map(([key, groupDots]) => ({
        type: 'scatter',
        mode: labelsOn ? 'markers+text' : 'markers',
        name: key,
        x: groupDots.map(d => d.x),
        y: groupDots.map(d => d.y),
        // `text` is what Plotly renders ON the dot, so the hover payload has to
        // live on `hovertext` — same split the highlight trace already uses.
        text: labelsOn ? groupDots.map(d => d.name) : undefined,
        textposition: 'top center',
        textfont: labelFont(),
        hovertext: groupDots.map(d => formatHover(d, x_meta, y_meta, color_meta, size_meta)),
        hovertemplate: '%{hovertext}<extra></extra>',
        marker: {
          size: size_meta ? groupDots.map(markerSize) : DEFAULT_SIZE,
          color: isTeamColor ? teamColor(key) : undefined,
          line: { color: MARKER_STROKE, width: 1 },
          opacity: baseOpacity,
        },
      }));
    } else {
      // Continuous color or no color
      const colorVals = color_meta
        ? nonHighlighted.map(d => (typeof d.color === 'number' ? d.color : 0))
        : undefined;
      baseTraces = [{
        type: 'scatter',
        mode: labelsOn ? 'markers+text' : 'markers',
        name: '',
        x: nonHighlighted.map(d => d.x),
        y: nonHighlighted.map(d => d.y),
        text: labelsOn ? nonHighlighted.map(d => d.name) : undefined,
        textposition: 'top center',
        textfont: labelFont(),
        hovertext: nonHighlighted.map(d => formatHover(d, x_meta, y_meta, color_meta, size_meta)),
        hovertemplate: '%{hovertext}<extra></extra>',
        marker: {
          size: size_meta ? nonHighlighted.map(markerSize) : DEFAULT_SIZE,
          color: colorVals ?? token('accent'),
          colorscale: colorVals ? 'Viridis' : undefined,
          showscale: !!colorVals,
          colorbar: colorVals
            ? {
                title: { text: color_meta!.label, font: { color: token('tx') } },
                tickfont: { color: token('tx-mut') },
                outlinecolor: token('edge'),
              }
            : undefined,
          line: { color: MARKER_STROKE, width: 1 },
          opacity: baseOpacity,
        },
      }];
    }

    // ----- highlight trace (one combined trace on top) -----
    if (highlighted.length > 0) {
      baseTraces.push({
        type: 'scatter',
        mode: 'markers+text',
        name: 'Highlighted',
        x: highlighted.map(d => d.x),
        y: highlighted.map(d => d.y),
        text: highlighted.map(d => d.name),
        textposition: 'top center',
        textfont: { color: token('accent'), size: 11, family: 'Inter, sans-serif' },
        hovertext: highlighted.map(d => formatHover(d, x_meta, y_meta, color_meta, size_meta)),
        hovertemplate: '%{hovertext}<extra></extra>',
        marker: {
          size: size_meta
            ? highlighted.map(d => Math.max(markerSize(d) + 4, 12))
            : 14,
          color: highlighted.map(d => {
            if (isTeamColor && typeof d.color === 'string') return teamColor(d.color);
            if (color_meta && typeof d.color === 'number') return token('accent');
            return token('accent');
          }),
          line: { color: token('accent'), width: 2.5 },
          opacity: 1,
        },
        showlegend: false,
      });
    }

    // ----- trendline trace(s) -----
    // Computed from ALL dots (highlighted + non-highlighted) so the line
    // represents the full population.
    if (trendline !== 'off' && dots.length >= 2) {
      if (trendline === 'global') {
        const fit = ols(dots);
        if (fit) {
          baseTraces.push(buildTrendlineTrace(fit, token('accent'), 'Trendline'));
        }
      } else if (trendline === 'per_group' && isCategoricalColor) {
        const groups = new Map<string, Dot[]>();
        for (const d of dots) {
          const key = d.color == null ? 'Unknown' : String(d.color);
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key)!.push(d);
        }
        for (const [key, gd] of groups) {
          if (gd.length < 3) continue; // 2 points always fits perfectly, misleading
          const fit = ols(gd);
          if (!fit) continue;
          const lineColor = isTeamColor ? teamColor(key) : token('accent');
          baseTraces.push(buildTrendlineTrace(fit, lineColor, `${key} trend`));
        }
      }
    }

    return baseTraces;
  }, [
    dots, color_meta, size_meta, isCategoricalColor, isTeamColor,
    x_meta, y_meta, highlightIds, highlights.length, trendline, labelsOn,
  ]);

  // Global trendline R² for the annotation badge
  const globalFit = useMemo(() => {
    if (trendline === 'off' || dots.length < 2) return null;
    return ols(dots);
  }, [dots, trendline]);

  // ── Pinned highlight readout ──────────────────────────────────────────────
  // One entry per highlighted player; each entry carries every dot currently
  // on the chart for that player (multi-season season-mode yields >1). When a
  // highlighted player has been filtered off the chart, dots is empty and the
  // card shows a muted "not on chart" note.
  const highlightReadout = useMemo(() => {
    return highlights.map(h => ({
      player_id: h.player_id,
      name: h.name,
      dots: dots.filter(d => d.player_id === h.player_id),
    }));
  }, [highlights, dots]);

  // Quadrant lines
  const shapes: Array<Record<string, unknown>> = [];
  if (showQuadrants) {
    if (chartData.medianX != null) {
      shapes.push({
        type: 'line',
        x0: chartData.medianX,
        x1: chartData.medianX,
        y0: chartData.yMin - chartData.yPad,
        y1: chartData.yMax + chartData.yPad,
        line: { color: token('edge'), width: 1, dash: 'dash' },
        layer: 'below',
      });
    }
    if (chartData.medianY != null) {
      shapes.push({
        type: 'line',
        x0: chartData.xMin - chartData.xPad,
        x1: chartData.xMax + chartData.xPad,
        y0: chartData.medianY,
        y1: chartData.medianY,
        line: { color: token('edge'), width: 1, dash: 'dash' },
        layer: 'below',
      });
    }
  }

  // Hide legend when too many categories (clutter)
  const showLegend =
    isCategoricalColor &&
    Array.isArray(traces) &&
    traces.length <= 35 &&
    traces.length > 1;

  const layout = {
    autosize: true,
    paper_bgcolor: 'transparent',
    plot_bgcolor: token('bg'),
    margin: { l: 70, r: 20, t: 30, b: 60 },
    xaxis: {
      title: { text: x_meta.label, font: { color: token('tx'), size: 14 } },
      gridcolor: token('edge-soft'),
      zerolinecolor: token('edge'),
      linecolor: token('edge'),
      tickfont: { color: token('tx-mut') },
      range: [chartData.xMin - chartData.xPad, chartData.xMax + chartData.xPad],
    },
    yaxis: {
      title: { text: y_meta.label, font: { color: token('tx'), size: 14 } },
      gridcolor: token('edge-soft'),
      zerolinecolor: token('edge'),
      linecolor: token('edge'),
      tickfont: { color: token('tx-mut') },
      range: [chartData.yMin - chartData.yPad, chartData.yMax + chartData.yPad],
    },
    showlegend: showLegend,
    legend: {
      font: { color: token('tx'), size: 11 },
      bgcolor: 'rgba(15, 20, 32, 0.85)',
      bordercolor: token('edge'),
      borderwidth: 1,
    },
    shapes,
    annotations: trendline === 'global' && globalFit
      ? [{
          xref: 'paper',
          yref: 'paper',
          x: 0.99,
          y: 0.98,
          xanchor: 'right',
          yanchor: 'top',
          text: `R² = ${globalFit.r2.toFixed(3)} · n = ${globalFit.n}`,
          showarrow: false,
          font: { color: token('accent'), size: 11, family: 'JetBrains Mono, monospace' },
          bgcolor: 'rgba(15, 20, 32, 0.85)',
          bordercolor: token('accent'),
          borderwidth: 1,
          borderpad: 4,
        }]
      : [],
    hoverlabel: {
      bgcolor: token('surf-2'),
      bordercolor: token('accent'),
      font: { color: token('tx'), family: 'Inter, sans-serif' },
    },
  };

  const config = {
    displaylogo: false,
    responsive: true,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
    toImageButtonOptions: {
      format: 'png',
      filename: `${x_meta.stat_id}_vs_${y_meta.stat_id}`,
      height: 800,
      width: 1200,
      scale: 2,
    },
  };

  return (
    <div className="relative w-full h-full">
      <Plot
        data={traces}
        layout={layout}
        config={config}
        style={{ width: '100%', height: '100%' }}
        useResizeHandler
      />

      {/* Pinned readout for highlighted players — persists until un-highlighted.
          pointer-events-none so it never blocks hovering the dots beneath it. */}
      {highlightReadout.length > 0 && (
        <div
          className="absolute top-3 left-[25%] -translate-x-1/2 z-10 pointer-events-none
                     max-w-[16rem] max-h-[calc(100%-1.5rem)] overflow-hidden
                     rounded-md border border-border bg-bg-card/90 backdrop-blur-sm
                     px-2.5 py-2 shadow-lg"
        >
          <div className="text-[9px] uppercase tracking-wider text-text-dim mb-1.5">
            Highlighted
          </div>
          <div className="flex flex-col gap-2">
            {highlightReadout.map(entry => {
              if (entry.dots.length === 0) {
                return (
                  <div key={entry.player_id} className="leading-tight">
                    <div className="text-[11px] font-semibold text-accent">{entry.name}</div>
                    <div className="text-[10px] text-text-dim">not on chart (filtered out)</div>
                  </div>
                );
              }
              return (
                <div key={entry.player_id} className="flex flex-col gap-1.5">
                  {entry.dots.map((d, i) => (
                    <ReadoutRow
                      key={`${entry.player_id}-${i}`}
                      dot={d}
                      xMeta={x_meta}
                      yMeta={y_meta}
                      colorMeta={color_meta}
                      sizeMeta={size_meta}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pinned-readout row
// ---------------------------------------------------------------------------

function ReadoutRow({
  dot, xMeta, yMeta, colorMeta, sizeMeta,
}: {
  dot: Dot;
  xMeta: StatMeta;
  yMeta: StatMeta;
  colorMeta: StatMeta | null;
  sizeMeta: StatMeta | null;
}) {
  // Team is already shown in the meta line, so skip the color stat when it's
  // just the team-color encoding (avoids a redundant "Team: MIN" line).
  const showColor =
    colorMeta != null && colorMeta.stat_id !== 'a_team' && dot.color != null;
  const showSize = sizeMeta != null && dot.size != null;

  const meta = [dot.pos, dot.team, dot.season]
    .filter(v => v != null && v !== '')
    .join(' · ');

  return (
    <div className="leading-tight">
      <div className="text-[11px] font-semibold text-accent">
        {dot.name}
        {meta && (
          <span className="ml-1 font-normal text-text-dim">{meta}</span>
        )}
      </div>
      <StatLine label={xMeta.label} value={formatStat(dot.x, xMeta.format_str)} />
      <StatLine label={yMeta.label} value={formatStat(dot.y, yMeta.format_str)} />
      {showColor && (
        <StatLine
          label={colorMeta!.label}
          value={formatStat(dot.color as number | string, colorMeta!.format_str)}
        />
      )}
      {showSize && (
        <StatLine
          label={sizeMeta!.label}
          value={formatStat(dot.size as number, sizeMeta!.format_str)}
        />
      )}
    </div>
  );
}

function StatLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-[11px] text-text-muted tabular-nums">
      <span className="text-text-dim">{label}:</span> {value}
    </div>
  );
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function median(nums: number[]): number {
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

function formatHover(
  d: Dot,
  xMeta: StatMeta,
  yMeta: StatMeta,
  colorMeta: StatMeta | null,
  sizeMeta: StatMeta | null,
): string {
  const lines = [
    `<b>${d.name}</b>`,
    `${d.pos} • ${d.team} • ${d.season}`,
    `${xMeta.label}: ${formatStat(d.x, xMeta.format_str)}`,
    `${yMeta.label}: ${formatStat(d.y, yMeta.format_str)}`,
  ];
  if (colorMeta && d.color != null) {
    lines.push(
      `${colorMeta.label}: ${formatStat(
        d.color as number | string,
        colorMeta.format_str,
      )}`,
    );
  }
  if (sizeMeta && d.size != null) {
    lines.push(`${sizeMeta.label}: ${formatStat(d.size, sizeMeta.format_str)}`);
  }
  return lines.join('<br>');
}

// ---------------------------------------------------------------------------
// Trendline (OLS) helpers
// ---------------------------------------------------------------------------

interface OLSFit {
  slope: number;
  intercept: number;
  r2: number;
  n: number;
  xMin: number;
  xMax: number;
}

/**
 * Ordinary least squares fit of y = slope*x + intercept.
 * Returns null when there aren't enough non-null pairs or x has zero variance.
 */
function ols(pairs: Dot[]): OLSFit | null {
  let n = 0;
  let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0, sumYY = 0;
  let xMin = Infinity, xMax = -Infinity;
  for (const d of pairs) {
    if (d.x == null || d.y == null) continue;
    n++;
    sumX += d.x;
    sumY += d.y;
    sumXY += d.x * d.y;
    sumXX += d.x * d.x;
    sumYY += d.y * d.y;
    if (d.x < xMin) xMin = d.x;
    if (d.x > xMax) xMax = d.x;
  }
  if (n < 2) return null;
  const denom = n * sumXX - sumX * sumX;
  if (Math.abs(denom) < 1e-12) return null; // x has zero variance
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;
  // R² via 1 - SSres/SStot
  const meanY = sumY / n;
  const ssTot = sumYY - n * meanY * meanY;
  // SSres = Σ(yᵢ - ŷᵢ)² = sumYY - intercept*sumY - slope*sumXY
  const ssRes = sumYY - intercept * sumY - slope * sumXY;
  const r2 = ssTot > 1e-12 ? Math.max(0, Math.min(1, 1 - ssRes / ssTot)) : 0;
  return { slope, intercept, r2, n, xMin, xMax };
}

function buildTrendlineTrace(fit: OLSFit, color: string, name: string) {
  const x0 = fit.xMin;
  const x1 = fit.xMax;
  return {
    type: 'scatter',
    mode: 'lines',
    name,
    x: [x0, x1],
    y: [fit.intercept + fit.slope * x0, fit.intercept + fit.slope * x1],
    line: {
      color,
      width: 2,
      dash: 'solid',
    },
    opacity: 0.8,
    hoverinfo: 'skip',
    showlegend: false,
  };
}
