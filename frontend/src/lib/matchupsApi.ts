// Positional Matchup Tool API client (Phase 3 of MATCHUP_TOOL_BUILD.md).
// Self-contained (own types + fetch), mirrors app/matchups.py.
//
// Everything the backend returns is already read-time computed: FP allowed is
// scored per request from raw stat sums, and every per-game figure is
// SUM(stat)/SUM(games) -- never an average of stored rates. Nothing here
// recomputes points client-side; the UI only formats what it is given.

const BASE = ''; // Flask serves /viz and /api on the same origin in prod

export const OFF_POSITIONS = ['QB', 'RB', 'WR', 'TE'] as const;
export const DEF_POSITIONS = ['DT', 'DE', 'LB', 'CB', 'S'] as const;
// Kicking lives on its own side ('st'), matching how the row is stored -- see
// build_matchup_table.py. PK is scored by a documented house default, not by
// any league's rules; the API reports mode 'default_pk' and says so.
export const ST_POSITIONS = ['PK'] as const;
export type Position =
  | (typeof OFF_POSITIONS)[number]
  | (typeof DEF_POSITIONS)[number]
  | (typeof ST_POSITIONS)[number];
export type Side = 'off' | 'def' | 'st';

export interface ScoringOption {
  id: string;
  name: string;
  /** True for Sleeper leagues, which are OFFENSE-ONLY: they carry no IDP
   *  scoring (they use team D/ST, which this DB does not model), so the API
   *  refuses them for IDP positions. The UI hides them on the IDP side rather
   *  than letting the request 400. */
  off_only?: boolean;
}

export interface MatchupMeta {
  seasons: number[];
  weeks: number[];
  /** The season and week this tool should OPEN on, derived server-side from
   *  the data (app/season_ctx.py). `week` is the UPCOMING one -- the tool
   *  projects forward -- and is clamped so a closed season cannot return a
   *  week past its end. Optional so an older server response still parses. */
  latest?: { season: number | null; week: number | null };
  teams: string[];
  positions: { off: string[]; def: string[] };
  scoring_options: ScoringOption[];
  notes: string[];
}

export interface UnscoredComponent {
  component: string;
  reason: string;
}

/** Describes how the returned points were computed. `unscored_components` is
 *  deliberately surfaced in the UI: columns with no matching league event code
 *  contribute nothing, and the tool says so rather than silently zeroing. */
export interface ScoringMeta {
  mode: 'ppr' | 'league';
  league_id: string | null;
  league_name: string | null;
  rule_source: string | null;
  scored_components: string[];
  unscored_components: UnscoredComponent[];
  mapping_notes: string[];
  /** Empirical per-position IDP rescale (median reported/predicted from
   *  `fantasy_scores`). Present only for IDP positions in league mode; null
   *  for offense, generic PPR, or `?calibrate=0`. Corrects the OI-8 DL/DB
   *  understatement so CROSS-position comparison is valid — within-position
   *  order and the matchup multiplier are ratios in which it cancels. */
  idp_calibration: number | null;
}

export interface RankingRow {
  rank: number;
  team: string;
  games: number;
  players_per_game: number;
  fp_allowed_total: number;
  fp_allowed_per_game: number;
  descriptive_per_game: Record<string, number>;
}

export interface PlayerRow {
  player_id: string;
  name: string;
  position: string;
  team: string;
  opponent: string;
  opponent_rank: number;
  opponent_fp_allowed_per_game: number;
  recent_games: number;
  recent_raw: Record<string, number>;
  recent_fp_per_game: number;
  /** Opponent difficulty as a league-average-centered ratio: >1 = easier than
   *  average (opponent allows more), <1 = tougher. */
  matchup_multiplier: number;
  /** recent_fp_per_game x matchup_multiplier. This is what the list is
   *  sorted by (see RankingsResponse.player_sort). */
  projected_fp_per_game: number;
  /** True when this slug carried rows for more than one team in the recent
   *  window -- a known two-human slug collision. Flagged, never merged. */
  collision: boolean;
}

export interface RankingsResponse {
  season: number;
  week: number | null;
  position: Position;
  side: Side;
  scoring: ScoringMeta;
  week_range: { from: number; to: number } | null;
  descriptive_columns: string[];
  rankings: RankingRow[];
  players: PlayerRow[];
  /** Human-readable description of how `players` is ordered. */
  player_sort?: string;
  warnings: string[];
}

export interface TrendPoint {
  week: number;
  fp_allowed: number;
  fp_allowed_per_game: number | null;
}

export interface RollingPoint {
  week: number;
  weeks_in_window: number;
  fp_allowed_per_game: number | null;
}

export interface TrendSeries {
  team: string;
  season_fp_allowed_per_game: number | null;
  weekly: TrendPoint[];
  last4_rolling: RollingPoint[];
}

export interface TrendsResponse {
  season: number;
  position: Position;
  side: Side;
  scoring: ScoringMeta;
  series: TrendSeries[];
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.error || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function fetchMatchupMeta(): Promise<MatchupMeta> {
  return getJSON<MatchupMeta>(`${BASE}/api/matchups/meta`);
}

export function fetchRankings(params: {
  season: number;
  week?: number | null;
  position: Position;
  scoring: string;
}): Promise<RankingsResponse> {
  const u = new URLSearchParams({
    season: String(params.season),
    position: params.position,
    scoring: params.scoring,
  });
  if (params.week != null) u.set('week', String(params.week));
  return getJSON<RankingsResponse>(`${BASE}/api/matchups/rankings?${u}`);
}

export function fetchTrends(params: {
  season: number;
  position: Position;
  scoring: string;
  teams: string[];
}): Promise<TrendsResponse> {
  const u = new URLSearchParams({
    season: String(params.season),
    position: params.position,
    scoring: params.scoring,
  });
  if (params.teams.length) u.set('teams', params.teams.join(','));
  return getJSON<TrendsResponse>(`${BASE}/api/matchups/trends?${u}`);
}

/** Human labels for the raw stat columns the API returns. Kept here so the
 *  page never has to guess at a column name. */
export const STAT_LABELS: Record<string, string> = {
  pass_attempts: 'Att', completions: 'Cmp', pass_yards: 'Pass Yd',
  pass_tds: 'Pass TD', interceptions: 'INT', sacks: 'Sacked',
  sack_yards: 'Sack Yd', carries: 'Car', rush_yards: 'Rush Yd',
  rush_tds: 'Rush TD', targets: 'Tgt', receptions: 'Rec',
  rec_yards: 'Rec Yd', rec_tds: 'Rec TD', fumbles: 'Fum',
  passing_2pt: 'Pass 2PT', rushing_2pt: 'Rush 2PT', receiving_2pt: 'Rec 2PT',
  passing_first_downs: 'Pass 1D', rushing_first_downs: 'Rush 1D',
  receiving_first_downs: 'Rec 1D', special_teams_tds: 'ST TD',
  def_tackles: 'Tkl', def_assists: 'Ast', def_tfl: 'TFL', def_sacks: 'Sk',
  def_qb_hits: 'QB Hit', def_pass_breakups: 'PBU', def_batted_passes: 'Bat',
  def_interceptions: 'INT', def_int_tds: 'INT TD',
  def_forced_fumbles: 'FF', def_fumble_recoveries: 'FR', def_fr_tds: 'FR TD',
  def_safeties: 'Sfty', def_tds: 'DEF TD', def_stops: 'Stops',
  def_pressures: 'Prs', def_snaps: 'Snaps', def_cov_targets: 'Cov Tgt',
  def_cov_receptions: 'Cov Rec', def_cov_yards: 'Cov Yd',
};

export function statLabel(col: string): string {
  return STAT_LABELS[col] ?? col;
}
