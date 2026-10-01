import { useMemo } from 'react';
import type { Dispatch } from 'react';
import type { StatMeta, Dot, SeasonsResponse } from '@/types/api';
import type { AppState, Action } from '@/state/queryState';
import { Field, Toggle, Segmented } from '@/components/ui/primitives';
import { GranularityToggle } from '@/components/controls/GranularityToggle';
import { WeekPicker } from '@/components/controls/WeekPicker';
import { YearChips } from '@/components/controls/YearChips';
import { PositionPicker } from '@/components/controls/PositionPicker';
import { TeamPicker } from '@/components/controls/TeamPicker';
import { StatPicker } from '@/components/controls/StatPicker';
import { ThresholdSlider } from '@/components/controls/ThresholdSlider';
import { PersonnelFilter } from '@/components/controls/PersonnelFilter';
import { PlayerHighlight } from '@/components/controls/PlayerHighlight';
import { groupLabel, LABEL_CAP } from '@/lib/constants';
import type { TrendlineMode } from '@/state/queryState';

interface SidebarProps {
  registry: StatMeta[];
  seasons: SeasonsResponse | null;
  state: AppState;
  dispatch: Dispatch<Action>;
  /** Players currently on the chart — feeds the highlight search */
  visibleDots: Dot[];
  /** Closes the mobile off-canvas drawer. No-op/unused at lg+ where the
   *  sidebar is permanently visible (chunk 7b). */
  onRequestClose?: () => void;
}

export function Sidebar({
  registry, seasons, state, dispatch, visibleDots, onRequestClose,
}: SidebarProps) {
  const { config, showQuadrants, showLabels, highlights } = state;

  // Mirrors the gate in ScatterChart — the toggle stays on (so it re-engages
  // once the user filters down) but the sidebar has to say why nothing changed.
  const labelsSuppressed = visibleDots.length > LABEL_CAP;

  const xMeta = useMemo(
    () => registry.find(s => s.stat_id === config.x_stat) ?? null,
    [registry, config.x_stat],
  );
  const yMeta = useMemo(
    () => registry.find(s => s.stat_id === config.y_stat) ?? null,
    [registry, config.y_stat],
  );

  // Source tables driving year availability — X and Y stats
  const activeTables = useMemo(() => {
    const t: string[] = [];
    if (xMeta) t.push(xMeta.source_table);
    if (yMeta && yMeta.source_table !== xMeta?.source_table) t.push(yMeta.source_table);
    return t;
  }, [xMeta, yMeta]);

  // Color/Size are NO LONGER table-scoped. As of 2026-07-20 BOTH backend paths
  // build a third-table extra through _build_side_cte -- the legacy path as a
  // LEFT JOINed CTE, and _query_two_cte (cross-source / career / week) as an
  // extra CTE at outer_key_grain. So any registry stat with a `player_id` on
  // its source table is a valid color/size dimension, in every granularity.
  //
  // History, because this line has been wrong in BOTH directions in one day:
  //   - originally an unconditional [X, Y, 'players'] filter, correct when the
  //     backend refused a third table everywhere. It went stale when the
  //     backend was widened, and silently hid the whole fpd fp/xfp family from
  //     Color/Size (diag_scat_03).
  //   - then briefly 'unrestricted only when season && same-source', which
  //     mirrored the legacy/two-CTE split -- also stale within hours, once
  //     two-CTE third-table support landed in a parallel session.
  // The lesson: a UI mirror of a backend capability drifts silently. If a
  // future change RE-narrows what the backend can join, prefer surfacing the
  // backend's own warning over reinstating a predictive filter here -- the
  // unjoinable cases already warn and drop the dimension rather than 400.
  const colorSizeTables = undefined;

  // Allowed positions for the current X+Y pair (intersection)
  const allowedPositions = useMemo(() => {
    if (!xMeta) return null;
    if (!yMeta) return xMeta.positions;
    return xMeta.positions.filter(p => yMeta.positions.includes(p));
  }, [xMeta, yMeta]);

  return (
    <aside className="w-96 max-w-[85vw] shrink-0 border-r border-border bg-bg-card flex flex-col h-full">
      <div className="px-4 py-2.5 border-b border-border">
        <a
          href="/"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-text-dim hover:text-text transition-colors"
        >
          <span aria-hidden="true">←</span> Back to Hub
        </a>
      </div>

      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-text">Controls</h2>
          <p className="text-[10px] text-text-dim mt-0.5">
            {registry.length} stats available
          </p>
        </div>
        {onRequestClose && (
          <button
            type="button"
            onClick={onRequestClose}
            className="lg:hidden h-7 w-7 shrink-0 rounded-md inline-flex items-center justify-center
                       text-text-muted hover:text-text hover:bg-bg-hover transition-colors"
            aria-label="Close filters"
          >
            ✕
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">

        {/* Granularity */}
        <Field label="Granularity">
          <GranularityToggle
            value={config.granularity}
            onChange={(g) => dispatch({ type: 'set_granularity', value: g })}
          />
        </Field>

        {/* Week — visible only when granularity = Week */}
        {config.granularity === 'week' && (
          <Field
            label="Week"
            hint={config.week == null ? 'pick a week' : `W${config.week}`}
          >
            <WeekPicker
              value={config.week ?? null}
              onChange={(w) => dispatch({ type: 'set_week', value: w })}
            />
          </Field>
        )}

        {/* Positions */}
        <Field label="Positions" hint={config.positions.length ? `${config.positions.length} on` : 'any'}>
          <PositionPicker
            selected={config.positions}
            onToggle={(p) => dispatch({ type: 'toggle_position', value: p })}
            allowedPositions={allowedPositions ?? undefined}
          />
        </Field>

        {/* Highlights */}
        <Field
          label="Highlight players"
          hint={highlights.length > 0 ? `${highlights.length}/3` : 'up to 3'}
        >
          <PlayerHighlight
            dots={visibleDots}
            highlights={highlights}
            onAdd={(h) => dispatch({ type: 'add_highlight', value: h })}
            onRemove={(id) => dispatch({ type: 'remove_highlight', value: id })}
            onClear={() => dispatch({ type: 'clear_highlights' })}
            config={config}
            xMeta={xMeta}
            yMeta={yMeta}
          />
          <div className="mt-2">
            <Toggle
              checked={showLabels}
              onChange={() => dispatch({ type: 'toggle_labels' })}
              label="Player names on dots"
            />
            {showLabels && labelsSuppressed && (
              <div className="mt-1 text-[10px] leading-snug text-text-dim">
                {visibleDots.length} dots on chart — names are hidden above{' '}
                {LABEL_CAP} because they overlap. Filter down to show them.
              </div>
            )}
          </div>
        </Field>

        {/* Teams */}
        <Field label="Teams">
          <TeamPicker
            selected={config.teams}
            onToggle={(t) => dispatch({ type: 'toggle_team', value: t })}
            onSet={(ts) => dispatch({ type: 'set_teams', value: ts })}
            onClear={() => dispatch({ type: 'clear_teams' })}
          />
        </Field>

        {/* Personnel — only available for weekly source tables */}
        <Field
          label="Personnel group"
          hint={
            !xMeta?.is_weekly_source
              ? 'weekly stats only'
              : config.personnel_group
                ? `≥ ${config.personnel_min_pct ?? 50}% of snaps`
                : undefined
          }
        >
          <PersonnelFilter
            group={config.personnel_group}
            minPct={config.personnel_min_pct}
            onSetGroup={(g) => dispatch({ type: 'set_personnel_group', value: g })}
            onSetMinPct={(p) => dispatch({ type: 'set_personnel_min_pct', value: p })}
            disabled={!xMeta?.is_weekly_source}
            disabledReason="Personnel filter is only available when X is a weekly-grain stat (game logs, NGS, snap counts, FF opportunity, PFF/FPD weekly tables)."
          />
        </Field>

        {/* Trendline */}
        <Field label="Trendline">
          <Segmented<TrendlineMode>
            value={state.trendline}
            onChange={(m) => dispatch({ type: 'set_trendline', value: m })}
            items={[
              { value: 'off', label: 'Off' },
              { value: 'global', label: 'Global' },
              {
                value: 'per_group',
                label: 'Per group',
                disabled: state.config.color_stat == null,
                title: state.config.color_stat == null
                  ? 'Select a categorical color stat to enable'
                  : undefined,
              },
            ]}
          />
        </Field>

        {/* X axis */}
        <Field
          label="X axis"
          hint={xMeta ? groupLabel(xMeta.source_group) : undefined}
        >
          <StatPicker
            stats={registry}
            value={config.x_stat}
            onChange={(id) => dispatch({ type: 'set_x_stat', value: id })}
            placeholder="Pick X stat"
            filterPositions={config.positions.length ? config.positions : undefined}
          />
        </Field>

        {/* Y axis */}
        <Field
          label="Y axis"
          hint={
            xMeta && yMeta && xMeta.source_table !== yMeta.source_table
              ? 'cross-source'
              : undefined
          }
        >
          <StatPicker
            stats={registry}
            value={config.y_stat}
            onChange={(id) => dispatch({ type: 'set_y_stat', value: id })}
            placeholder="Pick Y stat"
            filterPositions={config.positions.length ? config.positions : undefined}
          />
        </Field>

        {/* Color */}
        <Field
          label="Color"
          hint={xMeta || yMeta ? 'from X/Y or player attributes' : undefined}
        >
          <StatPicker
            stats={registry}
            value={config.color_stat}
            onChange={(id) => dispatch({ type: 'set_color_stat', value: id })}
            placeholder="(optional)"
            clearable
            restrictToTables={colorSizeTables}
          />
        </Field>

        {/* Size */}
        <Field
          label="Size"
          hint={xMeta || yMeta ? 'from X/Y or player attributes' : undefined}
        >
          <StatPicker
            stats={registry}
            value={config.size_stat}
            onChange={(id) => dispatch({ type: 'set_size_stat', value: id })}
            placeholder="(optional)"
            continuousOnly
            clearable
            restrictToTables={colorSizeTables}
          />
        </Field>

        {/* Threshold */}
        <Field
          label="Min threshold"
          hint={xMeta?.threshold_column ?? undefined}
        >
          <ThresholdSlider
            xStat={xMeta}
            value={config.min_threshold}
            onChange={(v) => dispatch({ type: 'set_threshold', value: v })}
            granularity={config.granularity}
          />
        </Field>

        {/* Years */}
        <Field
          label={config.granularity === 'career' ? 'Seasons to include' : 'Seasons'}
          hint={
            config.granularity === 'career'
              ? `${config.seasons.length} aggregated`
              : `${config.seasons.length} selected`
          }
        >
          <YearChips
            selected={config.seasons}
            onToggle={(y) => dispatch({ type: 'toggle_season', value: y })}
            onSetAll={(ys) => dispatch({ type: 'set_seasons', value: ys })}
            seasonsByTable={seasons?.by_table ?? {}}
            activeTables={activeTables}
            hideShortcuts={config.granularity === 'career'}
          />
        </Field>

        {/* Display */}
        <Field label="Display">
          <Toggle
            checked={showQuadrants}
            onChange={() => dispatch({ type: 'toggle_quadrants' })}
            label="Median quadrant lines"
          />
        </Field>

      </div>
    </aside>
  );
}
