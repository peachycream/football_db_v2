import type {
  QueryConfig,
  Granularity,
  SavedViewSummary,
  SavedViewState,
} from '@/types/api';
import { recentSeasons } from '@/lib/seasonCtx';

// Highlighted players (max 3). Outline + label persist across config changes.
export interface Highlight {
  player_id: string;
  name: string;
}

export type TrendlineMode = 'off' | 'global' | 'per_group';

export interface AppState {
  config: QueryConfig;
  showQuadrants: boolean;
  showLabels: boolean;
  trendline: TrendlineMode;
  highlights: Highlight[];

  // Saved-view tracking (chunk 5).
  // loadedView is the SavedViewSummary the user picked (or just saved).
  // loadedSnapshot is the state at the moment of load — used to compute
  // the "dirty" bit by comparing against the current {config, showQuadrants,
  // trendline}. Highlights are intentionally not part of the snapshot
  // (they're a watch list that persists across loads, per spec).
  loadedView: SavedViewSummary | null;
  loadedSnapshot: SavedViewState | null;
}

export const INITIAL_STATE: AppState = {
  config: {
    granularity: 'season',
    // The two most recent seasons, derived. Same shape as the [2024, 2025]
    // literal this replaces -- a default SELECTION, not the available list
    // (that comes from /api/viz/seasons) -- so it keeps working next year.
    seasons: recentSeasons('scatter'),
    week: null,
    positions: ['WR'],
    teams: [],
    x_stat: 'ra_yprr',         // matches chunk 2 demo
    y_stat: 'ra_tprr',
    color_stat: 'a_team',
    size_stat: null,
    min_threshold: null,
    personnel_group: null,
    personnel_min_pct: null,
  },
  showQuadrants: true,
  showLabels: false,
  trendline: 'off',
  highlights: [],
  loadedView: null,
  loadedSnapshot: null,
};

export type Action =
  | { type: 'set_granularity'; value: Granularity }
  | { type: 'toggle_season'; value: number }
  | { type: 'set_seasons'; value: number[] }
  | { type: 'set_week'; value: number | null }
  | { type: 'toggle_position'; value: string }
  | { type: 'set_positions'; value: string[] }
  | { type: 'toggle_team'; value: string }
  | { type: 'set_teams'; value: string[] }
  | { type: 'clear_teams' }
  | { type: 'set_x_stat'; value: string | null }
  | { type: 'set_y_stat'; value: string | null }
  | { type: 'set_color_stat'; value: string | null }
  | { type: 'set_size_stat'; value: string | null }
  | { type: 'set_threshold'; value: number | null }
  | { type: 'set_personnel_group'; value: string | null }
  | { type: 'set_personnel_min_pct'; value: number | null }
  | { type: 'toggle_quadrants' }
  | { type: 'toggle_labels' }
  | { type: 'set_trendline'; value: TrendlineMode }
  | { type: 'add_highlight'; value: Highlight }
  | { type: 'remove_highlight'; value: string }
  | { type: 'clear_highlights' }
  | {
      type: 'load_view';
      value: {
        config: QueryConfig;
        showQuadrants: boolean;
        showLabels: boolean;
        trendline: TrendlineMode;
        /** When present, the load is attributed to a saved view (sets
         *  loadedView/loadedSnapshot so the dirty indicator and the "Update
         *  loaded view" button can engage). Omit for un-attributed loads
         *  like applying a chat suggestion. */
        summary?: SavedViewSummary;
      };
    }
  | {
      /** Mark the current state as the new "clean" baseline for the loaded
       *  view — used after a successful PUT (update) so the dirty indicator
       *  resets. The caller passes the summary returned by the server (which
       *  may have an updated name/description). */
      type: 'mark_view_saved';
      value: { summary: SavedViewSummary; snapshot: SavedViewState };
    }
  | { type: 'unload_view' };

export function reducer(state: AppState, action: Action): AppState {
  const cfg = state.config;
  switch (action.type) {
    case 'set_granularity':
      return { ...state, config: { ...cfg, granularity: action.value } };

    case 'toggle_season': {
      const seasons = cfg.seasons.includes(action.value)
        ? cfg.seasons.filter(s => s !== action.value)
        : [...cfg.seasons, action.value].sort((a, b) => a - b);
      return { ...state, config: { ...cfg, seasons } };
    }
    case 'set_seasons':
      return { ...state, config: { ...cfg, seasons: [...action.value].sort((a, b) => a - b) } };

    case 'set_week':
      return { ...state, config: { ...cfg, week: action.value } };

    case 'toggle_position': {
      const positions = cfg.positions.includes(action.value)
        ? cfg.positions.filter(p => p !== action.value)
        : [...cfg.positions, action.value];
      return { ...state, config: { ...cfg, positions } };
    }
    case 'set_positions':
      return { ...state, config: { ...cfg, positions: action.value } };

    case 'toggle_team': {
      const teams = cfg.teams.includes(action.value)
        ? cfg.teams.filter(t => t !== action.value)
        : [...cfg.teams, action.value];
      return { ...state, config: { ...cfg, teams } };
    }
    case 'set_teams':
      return { ...state, config: { ...cfg, teams: [...action.value] } };
    case 'clear_teams':
      return { ...state, config: { ...cfg, teams: [] } };

    case 'set_x_stat':
      // Clearing threshold and personnel filter on X stat change — both are
      // X-stat-specific (threshold is per-stat; personnel only applies to
      // weekly source tables and we can't validate that client-side here).
      return {
        ...state,
        config: {
          ...cfg,
          x_stat: action.value,
          min_threshold: null,
          personnel_group: null,
          personnel_min_pct: null,
        },
      };
    case 'set_y_stat':
      return { ...state, config: { ...cfg, y_stat: action.value } };
    case 'set_color_stat':
      return { ...state, config: { ...cfg, color_stat: action.value } };
    case 'set_size_stat':
      return { ...state, config: { ...cfg, size_stat: action.value } };

    case 'set_threshold':
      return { ...state, config: { ...cfg, min_threshold: action.value } };

    case 'set_personnel_group':
      return { ...state, config: { ...cfg, personnel_group: action.value } };
    case 'set_personnel_min_pct':
      return { ...state, config: { ...cfg, personnel_min_pct: action.value } };

    case 'toggle_quadrants':
      return { ...state, showQuadrants: !state.showQuadrants };

    case 'toggle_labels':
      return { ...state, showLabels: !state.showLabels };

    case 'set_trendline':
      return { ...state, trendline: action.value };

    case 'add_highlight': {
      if (state.highlights.find(h => h.player_id === action.value.player_id)) return state;
      if (state.highlights.length >= 3) return state;
      return { ...state, highlights: [...state.highlights, action.value] };
    }
    case 'remove_highlight':
      return {
        ...state,
        highlights: state.highlights.filter(h => h.player_id !== action.value),
      };
    case 'clear_highlights':
      return { ...state, highlights: [] };

    case 'load_view': {
      // Replace config + decoration state in one shot. Highlights are
      // a "watch list" per the chunk-3 design decision — preserved across
      // view loads. The view's payload is trusted (came from /api/viz/views
      // which we wrote ourselves), so no validation here.
      const v = action.value;
      const snapshot: SavedViewState = {
        config: v.config,
        showQuadrants: v.showQuadrants,
        showLabels: v.showLabels,
        trendline: v.trendline,
      };
      return {
        ...state,
        config: v.config,
        showQuadrants: v.showQuadrants,
        showLabels: v.showLabels,
        trendline: v.trendline,
        // Attribute the load to a saved view only when summary is provided.
        loadedView: v.summary ?? null,
        loadedSnapshot: v.summary ? snapshot : null,
      };
    }

    case 'mark_view_saved':
      // After a successful create/update, the current state becomes the new
      // "clean" baseline — dirty indicator should turn off.
      return {
        ...state,
        loadedView: action.value.summary,
        loadedSnapshot: action.value.snapshot,
      };

    case 'unload_view':
      return { ...state, loadedView: null, loadedSnapshot: null };

    default:
      return state;
  }
}
