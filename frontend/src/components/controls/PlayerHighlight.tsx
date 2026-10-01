import { useMemo, useState } from 'react';
import type { Dot, QueryConfig, StatMeta } from '@/types/api';
import type { Highlight } from '@/state/queryState';
import { Popover, SearchInput, Chip } from '@/components/ui/primitives';
import { SimilarPopover } from '@/components/SimilarPopover';
import { cn } from '@/lib/utils';

interface PlayerHighlightProps {
  /** Players visible in the current chart — search pool */
  dots: Dot[];
  highlights: Highlight[];
  onAdd: (h: Highlight) => void;
  onRemove: (playerId: string) => void;
  onClear: () => void;
  /** Current chart config + axis metadata — feeds the "⌕ similar" search
      on each highlight chip (Chunk 7 / Open Item #10). */
  config: QueryConfig;
  xMeta: StatMeta | null;
  yMeta: StatMeta | null;
}

export function PlayerHighlight({
  dots,
  highlights,
  onAdd,
  onRemove,
  onClear,
  config,
  xMeta,
  yMeta,
}: PlayerHighlightProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  // Unique player list from current dots
  const candidates = useMemo(() => {
    const seen = new Set<string>();
    const out: { player_id: string; name: string; team: string | null; pos: string | null }[] = [];
    for (const d of dots) {
      if (!d.player_id || seen.has(d.player_id)) continue;
      seen.add(d.player_id);
      out.push({
        player_id: d.player_id,
        name: d.name,
        team: d.team,
        pos: d.pos,
      });
    }
    out.sort((a, b) => a.name.localeCompare(b.name));
    return out;
  }, [dots]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates.slice(0, 50);
    return candidates
      .filter(c => c.name.toLowerCase().includes(q))
      .slice(0, 50);
  }, [candidates, query]);

  const limitReached = highlights.length >= 3;

  return (
    <div className="flex flex-col gap-1.5">
      <Popover
        open={open}
        onOpenChange={setOpen}
        disabled={limitReached}
        className="w-[20rem] max-h-[24rem] flex flex-col"
        trigger={
          <div
            role="button"
            tabIndex={limitReached ? -1 : 0}
            aria-disabled={limitReached}
            className={cn(
              'h-9 w-full rounded-md bg-bg-elevated border border-border',
              'px-2.5 text-sm flex items-center justify-between cursor-pointer',
              'hover:border-border/70 focus:outline-none focus:border-accent/50',
              'focus:ring-1 focus:ring-accent/20 transition-colors',
              limitReached && 'opacity-40 cursor-not-allowed hover:border-border',
            )}
          >
            <span className="text-text-dim">
              {limitReached ? 'Limit of 3 highlights reached' : 'Search to highlight…'}
            </span>
            <span className="text-[10px] text-text-dim">{highlights.length}/3</span>
          </div>
        }
      >
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder={`Search ${candidates.length} players in chart…`}
          autoFocus
        />
        <div className="overflow-y-auto py-1 flex-1">
          {filtered.length === 0 && (
            <div className="px-3 py-6 text-center text-xs text-text-dim">
              {candidates.length === 0
                ? 'Adjust filters to add players to the chart, then search.'
                : 'No players match.'}
            </div>
          )}
          {filtered.map(c => {
            const already = highlights.some(h => h.player_id === c.player_id);
            return (
              <button
                key={c.player_id}
                type="button"
                disabled={already}
                onClick={() => {
                  onAdd({ player_id: c.player_id, name: c.name });
                  setQuery('');
                  setOpen(false);
                }}
                className={cn(
                  'w-full text-left px-3 py-1.5 flex items-center justify-between gap-2',
                  'hover:bg-bg-elevated transition-colors',
                  already && 'opacity-50 cursor-not-allowed hover:bg-transparent',
                )}
              >
                <span className="text-sm text-text truncate">{c.name}</span>
                <span className="text-[10px] text-text-dim font-mono shrink-0">
                  {c.pos} · {c.team}
                </span>
              </button>
            );
          })}
        </div>
      </Popover>

      {highlights.length > 0 && (
        <div className="flex flex-wrap gap-1 items-center">
          {highlights.map(h => (
            <div key={h.player_id} className="flex items-center gap-0.5">
              <Chip
                selected
                onClick={() => onRemove(h.player_id)}
                title="Click to remove"
                className="gap-1"
              >
                {h.name}
                <span className="text-accent/60 ml-1">×</span>
              </Chip>
              <SimilarPopover
                anchor={h}
                config={config}
                xMeta={xMeta}
                yMeta={yMeta}
                dotsCount={dots.length}
                highlights={highlights}
                onAdd={onAdd}
              />
            </div>
          ))}
          {highlights.length > 1 && (
            <button
              type="button"
              onClick={onClear}
              className="text-[10px] text-text-dim hover:text-text px-1.5"
            >
              clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}
