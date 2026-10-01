// Team Offensive Environment Dashboard API client. Self-contained (own types
// + fetch), mirrors app/offenv_api.py. Personnel (spec section 6) is Phase 3
// -- not modeled here yet.

import { seasonList } from './seasonCtx';

const BASE = ''; // Flask serves /viz and /api on the same origin in prod

export const OFFENV_TEAMS = [
  'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN',
  'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC', 'LA', 'LAC', 'LV', 'MIA',
  'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB',
  'TEN', 'WAS',
] as const;
export type OffenvTeam = (typeof OFFENV_TEAMS)[number];

// Derived from team_env_weekly -- the table this dashboard renders, and
// deliberately NOT the max across everything /viz/offense touches. That
// table carries no 2026 rows yet, so this list correctly stops short while
// the other dashboards move on, and self-corrects when its loader runs.
export const OFFENV_SEASONS: readonly number[] = seasonList('offense');

export const CORE_SPLITS = ['all', 'pass', 'rush', 'neutral', 'neutral_pass', 'neutral_rush'] as const;
export type CoreSplit = (typeof CORE_SPLITS)[number];

export interface MetricObj {
  v: number | null;
  pct: number | null;
  /** 1-indexed league rank (1 = best), present whenever pct is non-null. */
  rank?: number;
  n_teams?: number;
  n?: number;
}

export interface SplitMetrics {
  n: number;
  epa_per_play: MetricObj;
  success_rate: MetricObj;
  cpoe: MetricObj;
  explosive_rate: MetricObj;
  adot: MetricObj;
  proe: MetricObj;
  sack_rate: MetricObj;
  pa_rate: MetricObj;
  pa_epa: MetricObj;
  screen_rate: MetricObj;
  sec_per_snap: MetricObj;
  no_huddle_rate: MetricObj;
  pts_per_drive: MetricObj;
  drive_success: MetricObj;
  third_down_rate: MetricObj;
  early_down_pass_rate: MetricObj;
  rz_td_rate: MetricObj;
}

export interface LeagueTableRow {
  team: string;
  epa_play: number | null;
  proe: number | null;
  pace: number | null;
  success_rate: number | null;
}

export interface PersonnelRow {
  grp: string; // "11" | "12" | "21" | "13" | "10" | "22" | "other"
  snap_share: number;
  epa_play: number | null;
  pass_rate: number | null;
  pct_usage: number | null;
}

export interface PersonnelCoverage {
  weeks_present: number[];
  weeks_missing: number[];
}

type TrendSeries = {
  epa_play: [number, number | null][];
  proe: [number, number | null][];
  success_rate: [number, number | null][];
  pace: [number, number | null][];
  explosive_rate: [number, number | null][];
};

export interface GameInfo {
  opponent: string;
  home_away: 'home' | 'away';
  team_score: number | null;
  opp_score: number | null;
  result: 'W' | 'L' | 'T' | null;
}

export interface TargetRateByPosition {
  RB: MetricObj;
  WR: MetricObj;
  TE: MetricObj;
}

export interface TeamOffenseEnvResponse {
  team: string;
  season: number;
  weeks: [number, number];
  side: string;
  header: {
    record: string | null;
    epa_play: MetricObj;
    proe: MetricObj;
    pace: MetricObj;
    plays_per_game: MetricObj;
    game: GameInfo | null;
  };
  splits: Record<CoreSplit, SplitMetrics>;
  target_rate_by_position: TargetRateByPosition;
  personnel: PersonnelRow[];
  personnel_coverage: PersonnelCoverage;
  trend: TrendSeries;
  trend_league_median: TrendSeries;
  context: {
    pass_block_grade: MetricObj;
    pressure_rate_allowed: MetricObj;
  };
  league_table: LeagueTableRow[];
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

export function fetchTeamOffenseEnv(params: {
  season: number;
  team: string;
  weekStart: number;
  weekEnd: number;
}): Promise<TeamOffenseEnvResponse> {
  const u = new URLSearchParams({
    season: String(params.season),
    team: params.team,
    week_start: String(params.weekStart),
    week_end: String(params.weekEnd),
    side: 'off',
  });
  return getJSON<TeamOffenseEnvResponse>(`${BASE}/api/team-offense-env?${u}`);
}
