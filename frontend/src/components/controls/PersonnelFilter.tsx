import { useState } from 'react';
import { Popover, Slider, Button } from '@/components/ui/primitives';
import { cn } from '@/lib/utils';

// NFL offensive personnel groupings. Format: RB count + TE count
// (third digit is implied WR count to total 5 skill players).
const PERSONNEL_GROUPS: Array<{ id: string; label: string; desc: string }> = [
  { id: '11', label: '11', desc: '1 RB · 1 TE · 3 WR' },
  { id: '12', label: '12', desc: '1 RB · 2 TE · 2 WR' },
  { id: '13', label: '13', desc: '1 RB · 3 TE · 1 WR' },
  { id: '10', label: '10', desc: '1 RB · 0 TE · 4 WR' },
  { id: '21', label: '21', desc: '2 RB · 1 TE · 2 WR' },
  { id: '22', label: '22', desc: '2 RB · 2 TE · 1 WR' },
  { id: '20', label: '20', desc: '2 RB · 0 TE · 3 WR' },
  { id: '23', label: '23', desc: '2 RB · 3 TE · 0 WR' },
];

interface PersonnelFilterProps {
  group: string | null;
  minPct: number | null;
  onSetGroup: (g: string | null) => void;
  onSetMinPct: (pct: number | null) => void;
  /** When true, control is greyed out (e.g. source table is not weekly). */
  disabled?: boolean;
  disabledReason?: string;
}

export function PersonnelFilter({
  group, minPct, onSetGroup, onSetMinPct, disabled, disabledReason,
}: PersonnelFilterProps) {
  const [open, setOpen] = useState(false);
  const selected = PERSONNEL_GROUPS.find(g => g.id === group);

  const effectivePct = minPct ?? 50;

  return (
    <div className="flex flex-col gap-2">
      <Popover
        open={open}
        onOpenChange={setOpen}
        disabled={disabled}
        className="w-[16rem]"
        trigger={
          <div
            role="button"
            tabIndex={disabled ? -1 : 0}
            aria-disabled={disabled}
            title={disabled ? disabledReason : undefined}
            className={cn(
              'h-9 w-full rounded-md bg-bg-elevated border border-border',
              'px-2.5 text-sm flex items-center justify-between gap-2 cursor-pointer',
              'hover:border-border/70 focus:outline-none focus:border-accent/50',
              'focus:ring-1 focus:ring-accent/20 transition-colors',
              disabled && 'opacity-40 cursor-not-allowed hover:border-border',
            )}
          >
            {selected ? (
              <span className="flex items-center gap-2 min-w-0">
                <span className="text-text font-mono">{selected.label}</span>
                <span className="text-[10px] text-text-dim truncate">
                  {selected.desc}
                </span>
              </span>
            ) : (
              <span className="text-text-dim">Any personnel group</span>
            )}
            {selected && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onSetGroup(null);
                  onSetMinPct(null);
                }}
                className="text-text-dim hover:text-error text-xs px-1"
                title="Clear"
              >
                ×
              </button>
            )}
          </div>
        }
      >
        <div className="p-2 grid grid-cols-2 gap-1 max-h-[18rem] overflow-y-auto">
          {PERSONNEL_GROUPS.map(g => (
            <button
              key={g.id}
              type="button"
              onClick={() => {
                onSetGroup(g.id);
                if (minPct == null) onSetMinPct(50);
                setOpen(false);
              }}
              className={cn(
                'flex flex-col items-start gap-0.5 px-2.5 py-1.5 rounded-md',
                'border text-left transition-colors',
                'focus:outline-none focus:ring-1 focus:ring-accent/40',
                g.id === group
                  ? 'bg-accent/15 border-accent/50'
                  : 'bg-bg-elevated border-border hover:border-border/70',
              )}
            >
              <span className={cn(
                'text-sm font-mono font-medium',
                g.id === group ? 'text-accent' : 'text-text',
              )}>
                {g.label}
              </span>
              <span className="text-[10px] text-text-dim leading-tight">
                {g.desc}
              </span>
            </button>
          ))}
        </div>
        <div className="border-t border-border px-3 py-1.5 text-[10px] text-text-dim leading-relaxed">
          Filters to weeks where the team ran this personnel ≥ N% of plays.
        </div>
      </Popover>

      {selected && !disabled && (
        <>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-text-muted">
                Min snap %:
                <span className="text-accent font-mono ml-1.5">{effectivePct}%</span>
              </span>
              {minPct !== null && minPct !== 50 && (
                <Button variant="ghost" size="sm" onClick={() => onSetMinPct(50)}>
                  reset
                </Button>
              )}
            </div>
            <Slider
              min={0}
              max={100}
              step={5}
              value={effectivePct}
              onChange={onSetMinPct}
            />
          </div>
        </>
      )}
    </div>
  );
}
