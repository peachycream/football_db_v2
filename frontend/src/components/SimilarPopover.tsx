import { useEffect, useState } from 'react';
import type { QueryConfig, SimilarRow, StatMeta } from '@/types/api';
import type { Highlight } from '@/state/queryState';
import { findSimilar } from '@/lib/api';
import { Popover } from '@/components/ui/primitives';
import { cn } from '@/lib/utils';

// Similar-player search popover (Chunk 7 / Open Item #10). One instance per
// highlight chip in PlayerHighlight.tsx — clicking the "⌕" trigger next to a
// chip opens a small popover listing the N nearest players to that anchor in
// z-score-normalized (x, y) space, under the CURRENT chart config (same axes/
// filters/season scope the anchor is plotted under). Backend: POST
// /api/viz/similar.

interface SimilarPopoverProps {
  anchor: Highlight;
  config: QueryConfig;
  xMeta: StatMeta | null;
  yMeta: StatMeta | null;
  /** Dots currently visible in the chart — used only for the <6 hide rule
      per the design doc (excluding the anchor, need 5+ to fill n=5). */
  dotsCount: number;
  highlights: Highlight[];
  onAdd: (h: Highlight) => void;
}

function SimilarIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.5" y2="16.5" />
    </svg>
  );
}

export function SimilarPopover({
  anchor, config, xMeta, yMeta, dotsCount, highlights, onAdd,
}: SimilarPopoverProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<SimilarRow[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);

  // Hidden entirely (not just disabled) when the axes can't support a metric
  // distance, or there aren't enough other dots to fill n=5 — per design §3
  // "When the affordance is hidden / disabled".
  const hidden =
    xMeta?.value_type === 'categorical' ||
    yMeta?.value_type === 'categorical' ||
    dotsCount < 6;

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    findSimilar({ player_id: anchor.player_id, config, n: 5 })
      .then((r) => {
        if (cancelled) return;
        setRows(r.similar);
        setWarnings(r.warnings);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [open, anchor.player_id, config]);

  if (hidden) return null;

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      align="left"
      className="w-72 max-h-96 flex flex-col"
      trigger={
        <button
          type="button"
          title={`Find players similar to ${anchor.name}`}
          className={cn(
            'h-5 w-5 rounded flex items-center justify-center shrink-0',
            'text-text-dim hover:text-accent hover:bg-bg-elevated transition-colors',
            'focus:outline-none focus:ring-1 focus:ring-accent/40',
          )}
        >
          <SimilarIcon />
        </button>
      }
    >
      <div className="px-3 py-2 border-b border-border">
        <div className="text-xs font-medium text-text">Similar to {anchor.name}</div>
        <div className="text-[10px] text-text-dim mt-0.5">Nearest neighbors in the current chart</div>
      </div>

      {error && (
        <div className="px-3 py-1.5 text-[11px] text-error border-b border-border bg-bg-card">
          {error}
        </div>
      )}
      {!error && warnings.length > 0 && (
        <div className="px-3 py-1.5 text-[10px] text-text-dim border-b border-border bg-bg-card">
          {warnings.join(' ')}
        </div>
      )}

      <div className="overflow-y-auto flex-1 py-1">
        {loading && (
          <div className="px-3 py-4 text-xs text-text-dim text-center">Loading…</div>
        )}
        {!loading && !error && rows.length === 0 && (
          <div className="px-3 py-4 text-xs text-text-dim text-center">No similar players found.</div>
        )}
        {!loading && rows.map((r) => {
          const already = highlights.some(h => h.player_id === r.player_id);
          return (
            <div
              key={r.player_id}
              className="w-full px-3 py-1.5 flex items-center justify-between gap-2 hover:bg-bg-elevated transition-colors"
            >
              <div className="min-w-0">
                <div className="text-sm text-text truncate">{r.name}</div>
                <div className="text-[10px] text-text-dim font-mono">
                  {r.pos} · {r.team}{r.season != null ? ` · ${r.season}` : ''}
                </div>
              </div>
              <button
                type="button"
                disabled={already}
                title={already ? 'Already highlighted' : `Add ${r.name} as a highlight`}
                onClick={() => onAdd({ player_id: r.player_id, name: r.name })}
                className={cn(
                  'shrink-0 h-6 w-6 rounded flex items-center justify-center text-base leading-none',
                  'text-accent hover:bg-accent/15 transition-colors',
                  already && 'opacity-30 cursor-not-allowed hover:bg-transparent',
                )}
              >
                +
              </button>
            </div>
          );
        })}
      </div>
    </Popover>
  );
}
