import { useState } from 'react';
import { NFL_TEAMS } from '@/lib/constants';
import { TEAM_COLORS } from '@/lib/teamColors';
import { Popover, SearchInput, Button } from '@/components/ui/primitives';
import { cn } from '@/lib/utils';

interface TeamPickerProps {
  selected: string[];
  onToggle: (team: string) => void;
  onSet: (teams: string[]) => void;
  onClear: () => void;
}

export function TeamPicker({ selected, onToggle, onSet, onClear }: TeamPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const filteredTeams = query
    ? NFL_TEAMS.filter(t => t.toLowerCase().includes(query.toLowerCase()))
    : NFL_TEAMS;

  const labelText =
    selected.length === 0 ? 'All teams' :
    selected.length === 1 ? selected[0] :
    `${selected.length} teams`;

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      className="w-[22rem]"
      trigger={
        <div
          role="button"
          tabIndex={0}
          className={cn(
            'h-9 w-full rounded-md bg-bg-elevated border border-border',
            'px-2.5 text-sm flex items-center justify-between gap-2 cursor-pointer',
            'hover:border-border/70 focus:outline-none focus:border-accent/50',
            'focus:ring-1 focus:ring-accent/20 transition-colors',
          )}
        >
          <span className="flex items-center gap-1.5 min-w-0">
            {selected.length > 0 && selected.length <= 3 && (
              <span className="flex -space-x-1">
                {selected.slice(0, 3).map(t => (
                  <span
                    key={t}
                    className="w-3 h-3 rounded-full border border-bg-card"
                    style={{ backgroundColor: TEAM_COLORS[t] ?? 'var(--tx-mut)' }}
                  />
                ))}
              </span>
            )}
            <span className={selected.length ? 'text-text' : 'text-text-dim'}>
              {labelText}
            </span>
          </span>
          {selected.length > 0 && (
            <span className="text-[10px] text-text-dim font-mono">
              {selected.length}
            </span>
          )}
        </div>
      }
    >
      <SearchInput
        value={query}
        onChange={setQuery}
        placeholder="Search teams…"
        autoFocus
      />

      {/* Bulk action bar — always visible */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-border">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onSet([...NFL_TEAMS])}
        >
          Select all
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClear}
          disabled={selected.length === 0}
        >
          Clear
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onSet(NFL_TEAMS.filter(t => !selected.includes(t)))}
        >
          Invert
        </Button>
        <span className="ml-auto text-[10px] text-text-dim font-mono">
          {selected.length === 0 ? 'all 32' : `${selected.length}/32`}
        </span>
      </div>

      <div className="p-2 grid grid-cols-4 gap-1 max-h-[20rem] overflow-y-auto">
        {filteredTeams.map(team => {
          const isSelected = selected.includes(team);
          return (
            <div
              key={team}
              className={cn(
                'group relative rounded-md border transition-colors',
                'focus-within:ring-1 focus-within:ring-accent/40',
                isSelected
                  ? 'bg-accent/15 border-accent/50'
                  : 'bg-bg-elevated border-border hover:border-border/80',
              )}
            >
              <button
                type="button"
                onClick={() => onToggle(team)}
                className={cn(
                  'w-full px-2 py-1 text-xs font-mono font-medium',
                  'flex items-center justify-center gap-1',
                  'focus:outline-none',
                  isSelected ? 'text-accent' : 'text-text-muted hover:text-text',
                )}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: TEAM_COLORS[team] ?? 'var(--tx-mut)' }}
                />
                {team}
              </button>
              {/* "only" affordance — appears on hover */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onSet([team]);
                }}
                title={`Show only ${team}`}
                className={cn(
                  'absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full',
                  'bg-accent text-bg text-[9px] font-bold leading-none',
                  'flex items-center justify-center',
                  'opacity-0 group-hover:opacity-100 transition-opacity',
                  'focus:outline-none focus:opacity-100',
                  'hover:bg-accent-hover',
                )}
              >
                •
              </button>
            </div>
          );
        })}
        {filteredTeams.length === 0 && (
          <div className="col-span-4 py-4 text-center text-xs text-text-dim">
            No teams match "{query}".
          </div>
        )}
      </div>

      <div className="border-t border-border px-3 py-1.5 text-[10px] text-text-dim leading-relaxed">
        Hover a team for <span className="text-accent">•</span> to filter to only that team.
      </div>
    </Popover>
  );
}
