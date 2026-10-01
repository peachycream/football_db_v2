import { useMemo, useEffect } from 'react';
import type { StatMeta, Granularity } from '@/types/api';
import { Slider, Button } from '@/components/ui/primitives';

interface ThresholdSliderProps {
  xStat: StatMeta | null;
  value: number | null;
  onChange: (v: number | null) => void;
  /** Current granularity — in career mode the threshold is applied to the
   *  summed count across the selected seasons, so we adjust the hint. */
  granularity?: Granularity;
}

/**
 * The X stat's `threshold_column` (e.g. routes_run, targets) is the count
 * we filter on. `threshold_default` is the registry's suggestion (e.g. 200
 * routes for rate stats like YPRR). User can override with the slider or
 * type in a custom value.
 */
export function ThresholdSlider({ xStat, value, onChange, granularity }: ThresholdSliderProps) {
  const hasThreshold = !!(xStat?.threshold_column);
  const defaultVal = xStat?.threshold_default ?? null;
  const isCareer = granularity === 'career';

  // Reasonable upper bound for slider — 5x the default, or 1000 if no default.
  // In career mode the threshold filters the summed count across all selected
  // seasons, so allow a larger ceiling.
  const max = useMemo(() => {
    const careerMult = isCareer ? 4 : 1;
    if (!hasThreshold) return 100;
    if (defaultVal == null) return 1000 * careerMult;
    if (defaultVal === 0) return 100;
    return Math.max(50, Math.ceil(defaultVal * 5 / 10) * 10) * careerMult;
  }, [hasThreshold, defaultVal, isCareer]);

  // Auto-clear threshold when X stat changes to one without a threshold column.
  // The reducer already clears it on x_stat change, but if X is the same stat
  // remounting this component we still need to be sure.
  useEffect(() => {
    if (!hasThreshold && value !== null) onChange(null);
  }, [hasThreshold, value, onChange]);

  if (!hasThreshold) {
    return (
      <div className="text-xs text-text-dim italic px-1">
        No threshold for this stat
      </div>
    );
  }

  const effective = value ?? defaultVal ?? 0;

  return (
    <div className="flex flex-col gap-2">
      <Slider
        min={0}
        max={max}
        step={Math.max(1, Math.floor(max / 100))}
        value={effective}
        onChange={onChange}
      />
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-muted font-mono">
          {effective.toLocaleString()}
          <span className="text-text-dim ml-1">
            {xStat.threshold_column}{isCareer ? ' (career total)' : ''}
          </span>
        </span>
        {value !== null && defaultVal != null && value !== defaultVal && (
          <Button variant="ghost" size="sm" onClick={() => onChange(defaultVal)}>
            reset to {defaultVal}
          </Button>
        )}
      </div>
    </div>
  );
}
