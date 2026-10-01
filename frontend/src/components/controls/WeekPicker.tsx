import { cn } from '@/lib/utils';

interface WeekPickerProps {
  value: number | null;
  onChange: (week: number) => void;
}

/**
 * Single-select chip grid for NFL weeks. Regular season is 1-18; weeks 19-22
 * are postseason (Wild Card / Divisional / Conference / Super Bowl). Postseason
 * weeks render in a separate row, dimmer, to signal they're rarer to filter on.
 *
 * Unlike YearChips this is a single-select — week mode is grain, not aggregation.
 */
export function WeekPicker({ value, onChange }: WeekPickerProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {/* Regular season — 6 cols × 3 rows fits 1-18 cleanly */}
      <div className="grid grid-cols-6 gap-1">
        {Array.from({ length: 18 }, (_, i) => i + 1).map((w) => (
          <button
            key={w}
            type="button"
            onClick={() => onChange(w)}
            className={cn(
              'h-7 rounded text-[11px] font-mono tabular-nums transition-colors',
              'border focus:outline-none focus:ring-1 focus:ring-accent/40',
              w === value
                ? 'bg-accent/15 border-accent/40 text-accent'
                : 'bg-bg-elevated border-border text-text-muted hover:text-text hover:border-border/70',
            )}
          >
            {w.toString().padStart(2, '0')}
          </button>
        ))}
      </div>
      {/* Postseason — 4 chips, labeled */}
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] uppercase tracking-wider text-text-dim shrink-0">
          PO
        </span>
        <div className="grid grid-cols-4 gap-1 flex-1">
          {[
            { w: 19, label: 'WC' },
            { w: 20, label: 'DV' },
            { w: 21, label: 'CC' },
            { w: 22, label: 'SB' },
          ].map(({ w, label }) => (
            <button
              key={w}
              type="button"
              onClick={() => onChange(w)}
              title={
                w === 19 ? 'Wild Card'
                : w === 20 ? 'Divisional'
                : w === 21 ? 'Conference Championship'
                : 'Super Bowl'
              }
              className={cn(
                'h-7 rounded text-[10px] font-mono transition-colors',
                'border focus:outline-none focus:ring-1 focus:ring-accent/40',
                w === value
                  ? 'bg-accent/15 border-accent/40 text-accent'
                  : 'bg-bg-elevated border-border text-text-dim hover:text-text-muted hover:border-border/70',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
