// All 32 NFL franchises in the standard abbreviations the DB uses
// (post-normalization by viz_explorer.py).
export const NFL_TEAMS = [
  'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE',
  'DAL', 'DEN', 'DET', 'GB',  'HOU', 'IND', 'JAX', 'KC',
  'LA',  'LAC', 'LV',  'MIA', 'MIN', 'NE',  'NO',  'NYG',
  'NYJ', 'PHI', 'PIT', 'SEA', 'SF',  'TB',  'TEN', 'WAS',
] as const;

// Positions that the registry recognizes. Order matches the typical
// scout-pulldown order (skill -> trenches -> defense).
export const POSITIONS = {
  offense: ['QB', 'RB', 'FB', 'WR', 'TE'],
  oline:   ['OL', 'OT', 'OG', 'C'],
  defense: ['DE', 'DT', 'LB', 'CB', 'S'],
  special: ['K', 'P', 'LS'],
} as const;

export const ALL_POSITIONS = [
  ...POSITIONS.offense,
  ...POSITIONS.oline,
  ...POSITIONS.defense,
  ...POSITIONS.special,
];

// Max dots that may carry on-chart name labels. Plotly does no label
// decluttering, so above this the names overlap into an unreadable smear —
// the toggle stays on but suppresses itself and the sidebar says why.
// Shared between Sidebar (hint text) and ScatterChart (the actual gate);
// it lives here rather than in ScatterChart so the sidebar doesn't pull the
// lazy-loaded plotly chunk into the main bundle.
export const LABEL_CAP = 60;

// Year coverage advertised in the spec. Greyed-out individually based on
// the chosen source table's seasons from /api/viz/seasons.
export const YEAR_MIN = 2000;
export const YEAR_MAX = 2025;
export const ALL_YEARS = Array.from(
  { length: YEAR_MAX - YEAR_MIN + 1 },
  (_, i) => YEAR_MIN + i,
);

// Source-group display labels. The registry's source_group is snake_case
// and not user-friendly.
export const GROUP_LABELS: Record<string, string> = {
  attributes:       'Attributes',
  combine:          'Combine',
  contracts:        'Contracts',
  ff_opportunity:   'FF Opportunity',
  fpds_qb_depth:    'FPDS · QB Depth',
  fpds_receiving:   'FPDS · Receiving',
  fpds_rushing:     'FPDS · Rushing',
  idp_fantasy:      'IDP Fantasy',
  nfl_game_logs:    'Game Logs',
  ngs_passing:      'NGS · Passing',
  ngs_receiving:    'NGS · Receiving',
  ngs_rushing:      'NGS · Rushing',
  pff_defense:      'PFF · Defense',
  pff_grades:       'PFF · Grades',
  pff_passing:      'PFF · Passing',
  pff_receiving:    'PFF · Receiving',
  pff_rushing:      'PFF · Rushing',
  pfr_advstats:     'PFR Adv Stats',
  snap_counts:      'Snap Counts',
  trinity:          'Trinity Score',
};

export function groupLabel(group: string): string {
  return GROUP_LABELS[group] ?? group;
}

// Weekly-grain gating (personnel filter, future Week-mode granularity) used
// to be a hand-maintained table-name allowlist here. It drifted out of sync
// with stat_registry (11 tables added in the 2026-06-14 weekly-loader sprint
// were never added, silently disabling the personnel filter for ~440 stats;
// idp_fantasy_points was listed despite having no week column at all,
// silently enabling a control that would fail server-side). Replaced by
// `StatMeta.is_weekly_source`, computed server-side in viz_explorer.py's
// get_registry() from the same {week,season,team} check the query builder
// itself enforces — use `xMeta?.is_weekly_source` directly instead of a
// table-name lookup.
