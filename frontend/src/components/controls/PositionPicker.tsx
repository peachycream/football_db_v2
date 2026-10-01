import { POSITIONS } from '@/lib/constants';
import { Chip } from '@/components/ui/primitives';

interface PositionPickerProps {
  selected: string[];
  onToggle: (pos: string) => void;
  /** When provided, positions outside this set are visually muted. */
  allowedPositions?: string[] | null;
}

const SECTIONS: Array<{ title: string; positions: readonly string[] }> = [
  { title: 'Off', positions: POSITIONS.offense },
  { title: 'Def', positions: POSITIONS.defense },
];

export function PositionPicker({ selected, onToggle, allowedPositions }: PositionPickerProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {SECTIONS.map(section => (
        <div key={section.title} className="flex items-center gap-1.5">
          <span className="text-[10px] text-text-dim w-7 shrink-0">{section.title}</span>
          <div className="flex flex-wrap gap-1">
            {section.positions.map(pos => {
              const isAllowed = !allowedPositions || allowedPositions.includes(pos);
              return (
                <Chip
                  key={pos}
                  selected={selected.includes(pos)}
                  disabled={!isAllowed}
                  title={!isAllowed ? 'Not supported by the current stats' : undefined}
                  onClick={() => onToggle(pos)}
                  className="min-w-[2.5rem]"
                >
                  {pos}
                </Chip>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
