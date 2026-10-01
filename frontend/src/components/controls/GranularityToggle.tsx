import type { Granularity } from '@/types/api';
import { Segmented } from '@/components/ui/primitives';

interface GranularityToggleProps {
  value: Granularity;
  onChange: (g: Granularity) => void;
}

export function GranularityToggle({ value, onChange }: GranularityToggleProps) {
  return (
    <Segmented<Granularity>
      value={value}
      onChange={onChange}
      items={[
        { value: 'season', label: 'Season' },
        {
          value: 'week',
          label: 'Week',
          title: 'One dot per player for a single picked week.',
        },
        {
          value: 'career',
          label: 'Career',
          title: 'Aggregates selected seasons per player.',
        },
      ]}
    />
  );
}
