import { useMemo } from 'react';
import { ALL_YEARS } from '@/lib/constants';
import { Chip } from '@/components/ui/primitives';

interface YearChipsProps {
  selected: number[];
  onToggle: (year: number) => void;
  onSetAll: (years: number[]) => void;
  /** Mapping table_name -> available seasons. Years not in the intersection are greyed out. */
  seasonsByTable: Record<string, number[] | null>;
  /** The source tables in use for X & Y stats. Determines availability. */
  activeTables: string[];
  disabled?: boolean;
  /** When true, hide the "all available / 2024-25 / clear" shortcut row.
   *  Used in career mode where the season set is a deliberate choice and the
   *  bulk shortcuts are more likely to be hit by accident. Chips stay active. */
  hideShortcuts?: boolean;
}

export function YearChips({
  selected,
  onToggle,
  onSetAll,
  seasonsByTable,
  activeTables,
  disabled,
  hideShortcuts,
}: YearChipsProps) {
  // A year is available if every active source table has data for it.
  // (Or, for tables with null seasons — not season-scoped — we ignore them.)
  const availableYears = useMemo(() => {
    if (!activeTables.length) return new Set(ALL_YEARS);
    const sets: Set<number>[] = [];
    for (const t of activeTables) {
      const yrs = seasonsByTable[t];
      if (yrs == null) continue; // not season-scoped → no constraint
      sets.push(new Set(yrs));
    }
    if (!sets.length) return new Set(ALL_YEARS);
    return new Set(
      ALL_YEARS.filter(y => sets.every(s => s.has(y))),
    );
  }, [seasonsByTable, activeTables]);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="grid grid-cols-7 gap-1">
        {ALL_YEARS.map(year => {
          const isAvail = availableYears.has(year);
          const isSelected = selected.includes(year);
          return (
            <Chip
              key={year}
              selected={isSelected}
              disabled={disabled || !isAvail}
              title={!isAvail ? 'Not available for the selected stats' : undefined}
              onClick={() => onToggle(year)}
            >
              {String(year).slice(2)}
            </Chip>
          );
        })}
      </div>
      {!hideShortcuts && (
        <div className="flex gap-2 text-[10px] text-text-dim">
          <button
            type="button"
            onClick={() => onSetAll(Array.from(availableYears))}
            className="hover:text-text transition-colors"
          >
            all available
          </button>
          <span>·</span>
          <button
            type="button"
            onClick={() => {
              const recent = Array.from(availableYears).filter(y => y >= 2024);
              onSetAll(recent);
            }}
            className="hover:text-text transition-colors"
          >
            2024-25
          </button>
          <span>·</span>
          <button
            type="button"
            onClick={() => onSetAll([])}
            className="hover:text-text transition-colors"
          >
            clear
          </button>
        </div>
      )}
    </div>
  );
}
