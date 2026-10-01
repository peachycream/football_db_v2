import { useMemo, useState } from 'react';
import type { StatMeta } from '@/types/api';
import { groupLabel } from '@/lib/constants';
import { cn } from '@/lib/utils';
import { Popover, SearchInput } from '@/components/ui/primitives';

interface StatPickerProps {
  stats: StatMeta[];
  value: string | null;
  onChange: (statId: string | null) => void;
  placeholder?: string;
  /** When set, hide stats whose `positions` array has no overlap. */
  filterPositions?: string[];
  /** When true, only continuous-typed stats are listed. */
  continuousOnly?: boolean;
  /** When true, allow clearing the selection. */
  clearable?: boolean;
  /** When set, hide stats not from any of these source tables (e.g. enforce same-source). */
  restrictToTables?: string[];
}

export function StatPicker({
  stats,
  value,
  onChange,
  placeholder = 'Select a stat…',
  filterPositions,
  continuousOnly,
  clearable,
  restrictToTables,
}: StatPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const selected = stats.find(s => s.stat_id === value) ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return stats.filter(s => {
      if (continuousOnly && s.value_type !== 'continuous') return false;
      if (restrictToTables && restrictToTables.length && !restrictToTables.includes(s.source_table)) {
        return false;
      }
      if (filterPositions && filterPositions.length) {
        const overlap = s.positions.some(p => filterPositions.includes(p));
        if (!overlap) return false;
      }
      if (!q) return true;
      return (
        s.label.toLowerCase().includes(q) ||
        s.stat_id.toLowerCase().includes(q) ||
        s.source_group.toLowerCase().includes(q) ||
        (s.description ?? '').toLowerCase().includes(q)
      );
    });
  }, [stats, query, filterPositions, continuousOnly, restrictToTables]);

  // Group filtered stats by source_group for the dropdown
  const grouped = useMemo(() => {
    const map = new Map<string, StatMeta[]>();
    for (const s of filtered) {
      const g = s.source_group;
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(s);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      className="w-[22rem] max-h-[28rem] flex flex-col"
      trigger={
        <div
          role="button"
          tabIndex={0}
          className={cn(
            'group h-9 w-full rounded-md bg-bg-elevated border border-border',
            'px-2.5 text-left text-sm flex items-center justify-between gap-2 cursor-pointer',
            'hover:border-border/70 focus:outline-none focus:border-accent/50',
            'focus:ring-1 focus:ring-accent/20 transition-colors',
          )}
        >
          {selected ? (
            <span className="text-text truncate min-w-0">{selected.label}</span>
          ) : (
            <span className="text-text-dim">{placeholder}</span>
          )}
          <ChevronIcon />
        </div>
      }
    >
      <SearchInput
        value={query}
        onChange={setQuery}
        placeholder={`Search ${filtered.length} stats…`}
        autoFocus
      />

      <div className="overflow-y-auto py-1 flex-1">
        {clearable && value && (
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className="w-full text-left px-3 py-2 text-xs text-text-muted hover:bg-bg-elevated border-b border-border mb-1"
          >
            Clear selection
          </button>
        )}

        {grouped.length === 0 && (
          <div className="px-3 py-6 text-center text-xs text-text-dim">
            No stats match these filters.
          </div>
        )}

        {grouped.map(([group, items]) => (
          <div key={group}>
            <div className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wider text-text-dim font-semibold sticky top-0 bg-bg-card">
              {groupLabel(group)}
            </div>
            {items.map(stat => (
              <button
                key={stat.stat_id}
                type="button"
                onClick={() => {
                  onChange(stat.stat_id);
                  setOpen(false);
                  setQuery('');
                }}
                className={cn(
                  'w-full text-left px-3 py-1.5 flex items-baseline gap-2',
                  'hover:bg-bg-elevated transition-colors',
                  stat.stat_id === value && 'bg-accent/10',
                )}
                title={stat.description ?? undefined}
              >
                <span className={cn(
                  'flex-1 text-sm truncate',
                  stat.stat_id === value ? 'text-accent' : 'text-text',
                )}>
                  {stat.label}
                </span>
                <span className="text-[10px] text-text-dim font-mono shrink-0">
                  {stat.stat_id}
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </Popover>
  );
}

function ChevronIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="w-3.5 h-3.5 text-text-dim shrink-0"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
