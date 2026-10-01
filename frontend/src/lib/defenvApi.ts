// Team Defense Environment Dashboard API client. Self-contained (own types +
// fetch), mirrors app/team_def_env.py. Unlike offenvApi.ts's `splits` dict
// (team_env_weekly is LONG -- one row per split), team_def_env_weekly is
// WIDE (one row per season/week/defteam) -- so this response has named
// SECTIONS (volume_efficiency/pass_rush/coverage/run_defense/situational/
// havoc/grades) instead of a splits-by-key dict. See DEF_ENV_BUILD.md
// section 4 / DEF_ENV_LOG.md Phase 3 for why.

import { seasonList } from './seasonCtx';

const BASE = ''; // Flask serves /viz and /api on the same origin in prod

export const DEFENV_TEAMS = [
  'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN',
  'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC', 'LA', 'LAC', 'LV', 'MIA',
  'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB',
  'TEN', 'WAS',
] as const;
export type DefenvTeam = (typeof DEFENV_TEAMS)[number];

// Derived from team_def_env_weekly -- the table this dashboard renders.
export const DEFENV_SEASONS: readonly number[] = seasonList('defense');

export interface MetricObj {
  v: number | null;
  pct: number | null;
  /** 1-indexed league rank (1 = best), present whenever pct is non-null. */
  rank?: number;
  n_teams?: number;
  n?: number;
}

export interface GameInfo {
  opponent: string;
  home_away: 'home' | 'away';
  team_score: number | null;
  opp_score: number | null;
  result: 'W' | 'L' | 'T' | null;
}

export interface VolumeEfficiency {
  n: number;
  epa_per_play_allowed: MetricObj;
  success_rate_allowed: MetricObj;
  explosive_rate_allowed: MetricObj;
  pass_epa_per_play_allowed: MetricObj;
  rush_epa_per_play_allowed: MetricObj;
  early_epa_per_play: MetricObj;
  late_epa_per_play: MetricObj;
  proe_faced: MetricObj;
  neutral_sec_per_snap_faced: MetricObj;
  pts_per_drive_allowed: MetricObj;
}

export interface PassRush {
  pressure_rate: MetricObj;
  sack_rate_allowed: MetricObj;
  hurry_rate: MetricObj;
  qb_hit_rate: MetricObj;
  pressure_rate_4man_ftn: MetricObj;
}

export interface Coverage {
  comp_pct_allowed: MetricObj;
  yards_per_att_allowed: MetricObj;
  passer_rating_allowed: MetricObj;
  cpoe_allowed: MetricObj;
  yards_per_coverage_snap_allowed: MetricObj;
  deep_target_rate_allowed: MetricObj;
}

export interface RunDefense {
  rush_ypc_allowed: MetricObj;
  yco_per_att_allowed: MetricObj;
  stuff_rate: MetricObj;
}

export interface Situational {
  third_down_rate_allowed: MetricObj;
  rz_td_rate_allowed: MetricObj;
  three_and_out_rate_forced: MetricObj;
}

export interface Havoc {
  havoc_rate: MetricObj;
}

export interface Grades {
  def_grade: MetricObj;
  pass_rush_grade: MetricObj;
  coverage_grade: MetricObj;
  run_def_grade: MetricObj;
  tackle_grade: MetricObj;
}

export interface SchemeSection {
  through_season: number;
  man_zone?: {
    man_rate: number | null;
    zone_rate: number | null;
    epa_per_play_vs_man: number | null;
    epa_per_play_vs_zone: number | null;
  };
  coverage_shell?: Record<'cover0_rate' | 'cover1_rate' | 'cover2_rate' | 'cover3_rate' | 'cover4_rate' | 'cover6_rate' | 'other_rate', number | null>;
  personnel?: {
    base_rate: number | null;
    nickel_rate: number | null;
    dime_rate: number | null;
    other_rate: number | null;
  };
  blitz_rate?: number | null;
  box_counts?: {
    lightbox_ypc: number | null;
    heavybox_ypc: number | null;
  };
  pff_coverage?: {
    man_catch_rate: number | null;
    man_yards_per_target: number | null;
    zone_catch_rate: number | null;
    zone_yards_per_target: number | null;
  };
}

export interface LeagueTableRow {
  team: string;
  epa_play_allowed: number | null;
  success_rate_allowed: number | null;
  havoc_rate: number | null;
  pts_per_drive_allowed: number | null;
}

type TrendSeries = {
  epa_per_play_allowed: [number, number | null][];
  success_rate_allowed: [number, number | null][];
  havoc_rate: [number, number | null][];
  pts_per_drive_allowed: [number, number | null][];
};

export interface TeamDefenseEnvResponse {
  team: string;
  season: number;
  weeks: [number, number];
  header: {
    record_allowed: string | null;
    epa_play_allowed: MetricObj;
    havoc_rate: MetricObj;
    plays_faced_per_game: MetricObj;
    game: GameInfo | null;
  };
  volume_efficiency: VolumeEfficiency;
  pass_rush: PassRush;
  coverage: Coverage;
  run_defense: RunDefense;
  situational: Situational;
  havoc: Havoc;
  grades: Grades;
  scheme: SchemeSection | null;
  trend: TrendSeries;
  trend_league_median: TrendSeries;
  league_table: LeagueTableRow[];
}

export interface TeamDefenseGamedayResponse {
  team: string;
  season: number;
  week: number;
  volume_efficiency: { epa_per_play_allowed: MetricObj; success_rate_allowed: MetricObj };
  pass_rush: { pressure_rate: MetricObj; sack_rate_allowed: MetricObj };
  coverage: { comp_pct_allowed: MetricObj; passer_rating_allowed: MetricObj };
  run_defense: { rush_ypc_allowed: MetricObj; stuff_rate: MetricObj };
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

export function fetchTeamDefenseEnv(params: {
  season: number;
  team: string;
  weekStart: number;
  weekEnd: number;
}): Promise<TeamDefenseEnvResponse> {
  const u = new URLSearchParams({
    season: String(params.season),
    team: params.team,
    week_start: String(params.weekStart),
    week_end: String(params.weekEnd),
  });
  return getJSON<TeamDefenseEnvResponse>(`${BASE}/api/team-defense-env?${u}`);
}

export function fetchTeamDefenseGameday(params: {
  season: number;
  team: string;
}): Promise<TeamDefenseGamedayResponse> {
  const u = new URLSearchParams({ season: String(params.season), team: params.team });
  return getJSON<TeamDefenseGamedayResponse>(`${BASE}/api/team-defense-env/gameday?${u}`);
}
