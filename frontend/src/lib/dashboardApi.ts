// Dashboard API client. Self-contained (own types + fetch) so the existing
// lib/api.ts and types/api.ts stay untouched. Mirrors the /api/dashboard/*
// blueprint in app/dashboard.py (+ dashboard_tiles.py, dashboard_viz.py).

import { seasonList } from './seasonCtx';

const BASE = ''; // Flask serves /viz and /api on the same origin in prod

export interface DashSearchHit {
  player_id: string;
  full_name: string | null;
  position: string | null;
  team: string | null;
  side: 'offense' | 'defense' | null;
  bucket: string | null; // QB|RB|WR|TE|DE|DT|LB|CB|S
}

export interface DashPlayerListItem extends DashSearchHit {
  fantasy_total: number | null;
}

export interface DashHeader {
  player_id: string;
  full_name: string | null;
  position: string | null;
  bucket: string | null;
  side: 'offense' | 'defense' | null;
  team: string | null;
  season: number;
  league_id: string;
  fantasy_total: number | null;
  games: number | null;
  fantasy_ppg: number | null;
  fantasy_source: string | null;
  age: number | null;
  draft_year: number | null;
  scoring_label: string | null;
}

export interface DashLeague {
  league_id: string;
  label: string;
  enabled: boolean;
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

export function dashboardSearch(q: string, limit = 20): Promise<DashSearchHit[]> {
  const u = new URLSearchParams({ q, limit: String(limit) });
  return getJSON<DashSearchHit[]>(`${BASE}/api/dashboard/search?${u}`);
}

export function dashboardPlayers(params: {
  league_id: string;
  season: number;
  bucket?: string | null;
  team?: string | null;
  limit?: number;
}): Promise<DashPlayerListItem[]> {
  const u = new URLSearchParams({
    league_id: params.league_id,
    season: String(params.season),
    limit: String(params.limit ?? 100),
  });
  if (params.bucket) u.set('bucket', params.bucket);
  if (params.team) u.set('team', params.team);
  return getJSON<DashPlayerListItem[]>(`${BASE}/api/dashboard/players?${u}`);
}

export function dashboardHeader(
  playerId: string,
  season: number,
  leagueId: string,
): Promise<DashHeader> {
  const u = new URLSearchParams({
    player_id: playerId,
    season: String(season),
    league_id: leagueId,
  });
  return getJSON<DashHeader>(`${BASE}/api/dashboard/header?${u}`);
}

export function dashboardLeagues(): Promise<DashLeague[]> {
  return getJSON<DashLeague[]>(`${BASE}/api/dashboard/leagues`);
}

// ── Available seasons (deep-link default season) ────────────────────────────
// Added for PLAYER_LINK_NAV_BUILD.md Phase 2 — see app/dashboard.py's
// available_seasons() docstring for the "real activity" definition.
export interface DashAvailableSeasons {
  player_id: string;
  side: 'offense' | 'defense' | null;
  seasons: number[];
  most_recent: number | null;
}

export function dashboardAvailableSeasons(playerId: string): Promise<DashAvailableSeasons> {
  const u = new URLSearchParams({ player_id: playerId });
  return getJSON<DashAvailableSeasons>(`${BASE}/api/dashboard/available-seasons?${u}`);
}

// Bucket taxonomy + a few static lists used by the header dropdowns.
export const BUCKETS = ['QB', 'RB', 'WR', 'TE', 'DE', 'DT', 'LB', 'CB', 'S'] as const;
export type Bucket = (typeof BUCKETS)[number];

export const NFL_TEAMS = [
  'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN',
  'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC', 'LAC', 'LAR', 'LV', 'MIA',
  'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB',
  'TEN', 'WAS',
] as const;

// Derived server-side from nfl_game_logs, floored at 2021 -- where this
// dashboard's snap and PFF panels begin. See lib/seasonCtx.ts.
export const DASH_SEASONS: readonly number[] = seasonList('player');

// ── Tiles ───────────────────────────────────────────────────────────────────
export interface DashTile {
  n: number;
  label: string;
  star?: boolean;
  display?: string;
  raw?: number | null;
  sub?: string | null;
  percentile?: number | null;
  per_game?: boolean;
  league_dep?: boolean;
  warn?: boolean;
  blank?: boolean;
}

export interface DashTilesResponse {
  player_id: string;
  full_name: string | null;
  position: string | null;
  bucket: string | null;
  side: 'offense' | 'defense' | null;
  team: string | null;
  season: number;
  league_id: string;
  games: number | null;
  pool_size: number;
  tiles: DashTile[];
}

export function dashboardTiles(
  playerId: string,
  season: number,
  leagueId: string,
): Promise<DashTilesResponse> {
  const u = new URLSearchParams({
    player_id: playerId,
    season: String(season),
    league_id: leagueId,
  });
  return getJSON<DashTilesResponse>(`${BASE}/api/dashboard/tiles?${u}`);
}

// ── Snap trend (viz 1) ───────────────────────────────────────────────────────
export interface DashSnapPoint {
  week: number;
  snaps: number;
  snap_pct: number;        // 0-100, label-ready (backend pre-scales the 0-1 column)
  team: string | null;     // comma-joined if >1 team logged snaps that week
  multi_team: boolean;     // same-slug collision marker for the plotted side
}

export interface DashSnaps {
  player_id: string;
  full_name: string | null;
  position: string | null;
  bucket: string | null;
  side: 'offense' | 'defense' | null;
  season: number;
  side_label: string | null;
  points: DashSnapPoint[];
  season_high: number | null;
  collision_weeks: number;
}

export function dashboardSnaps(
  playerId: string,
  season: number,
): Promise<DashSnaps> {
  const u = new URLSearchParams({
    player_id: playerId,
    season: String(season),
  });
  return getJSON<DashSnaps>(`${BASE}/api/dashboard/snaps?${u}`);
}

// ── Trinity Score (WR/TE/RB; DD Fantasy Football's formula, ported) ─────────
export interface DashTrinityWeek {
  week: number;
  team: string;
  position: string;
  score: number;           // that week alone, against that week's WR/TE pool
  tier: string;
  rank: number;            // within position that week
  targets: number;
  rec: number;
  rec_yards: number;
  rec_td: number;
}

export interface DashTrinityThrough {
  week: number;
  position: string;
  score: number;           // weeks 1..week together (season to date)
  tier: string;
  rank: number;
  games: number;
  targets: number;
  rec: number;
  rec_yards: number;
  rec_td: number;
  pool?: number;           // summary row only: players ranked at this position
}

export interface DashTrinityStored {
  score: number;           // DD's own published season score (a different computation for some players)
  tier: string | null;
  rank: number | null;
  team: string | null;
  games: number | null;
  ppg: number | null;
}

export interface DashTrinity {
  player_id: string;
  full_name: string | null;
  position: string | null;
  bucket: string | null;
  season: number;
  supported: boolean;      // WR / TE / RB only
  first_season: number;    // DD's data starts here
  has_data: boolean;
  weekly: DashTrinityWeek[];
  through: DashTrinityThrough[];
  summary: DashTrinityThrough | null;
  stored: DashTrinityStored | null;
  withheld_weeks: number[]; // weeks DD's data is wrong at the source (never loaded)
  bands: { label: string; min: number }[];  // tier thresholds, high to low
}

export function dashboardTrinity(
  playerId: string,
  season: number,
): Promise<DashTrinity> {
  const u = new URLSearchParams({
    player_id: playerId,
    season: String(season),
  });
  return getJSON<DashTrinity>(`${BASE}/api/dashboard/trinity?${u}`);
}

// ── Route tree (viz 2) ───────────────────────────────────────────────────────
export interface DashRouteSpoke {
  key: string;
  label: string;
  routes: number;
  mix_pct: number;          // 0-100, computed share (Σ ≈ 100); NOT stored route_pct
  targets: number;          // tprr × routes, summed
  yprr: number | null;
  tprr: number | null;      // 0-1
  win_rate: number | null;  // 0-100
  sep_score: number | null; // raw yards, can be negative
  ador: number | null;      // raw yards; null for go
  receptions?: number;      // basis 'targets' only
  ypt?: number | null;      // basis 'targets' only: yards per target
}

export interface DashRoutes {
  player_id: string;
  full_name: string | null;
  position: string | null;
  bucket: string | null;
  side: 'offense' | 'defense' | null;
  season: number;
  has_data: boolean;
  // 'routes' = routes run per route type (FTN, 2026-); 'targets' = target share by the
  // targeted receiver's route (nflverse, 2016-2025: no routes-run denominator exists)
  basis?: 'routes' | 'targets';
  total_routes: number;
  total_targets: number;
  weeks: number;
  spokes: DashRouteSpoke[];
}

export function dashboardRoutes(
  playerId: string,
  season: number,
): Promise<DashRoutes> {
  const u = new URLSearchParams({
    player_id: playerId,
    season: String(season),
  });
  return getJSON<DashRoutes>(`${BASE}/api/dashboard/routes?${u}`);
}

// ── QB pass zones (Player Profile Sections Phase 1) ─────────────────────────
export interface DashQbZone {
  direction: 'left' | 'middle' | 'right';
  depth: 'blos' | 'short' | 'medium' | 'deep';
  attempts: number;
  att_share: number;        // 0-1
  comp_pct: number | null;  // 0-1
  cpoe: number | null;      // percentage points, e.g. 3.4 = +3.4pp
  epa_per_att: number | null;
}

export interface DashQbChip {
  value: number;
  pct: number; // 0-100 percentile rank within the eligible pool
}

export interface DashQbZonesHeader {
  epa_per_dropback: DashQbChip | null;
  cpoe: DashQbChip | null;
  success_rate: DashQbChip | null;
  fp_per_dropback: DashQbChip | null;
}

export interface DashQbZones {
  player_id: string;
  full_name: string | null;
  position: string | null;
  season: number;
  eligible: boolean;
  reason?: string;
  zones?: DashQbZone[];
  header?: DashQbZonesHeader;
  dropbacks?: number;
  min_dropbacks?: number;
}

export function dashboardQbZones(
  playerId: string,
  season: number,
  leagueId?: string | null,
): Promise<DashQbZones> {
  const params: Record<string, string> = { player_id: playerId, season: String(season) };
  if (leagueId && leagueId !== 'default') params.league_id = leagueId;
  const u = new URLSearchParams(params);
  return getJSON<DashQbZones>(`${BASE}/api/dashboard/qb-zones?${u}`);
}

// ── RB run lanes (Player Profile Sections Phase 2) ──────────────────────────
export interface DashRbLane {
  lane: 'LE' | 'LT' | 'LG' | 'M' | 'RG' | 'RT' | 'RE';
  carries: number;
  carry_share: number;          // 0-1
  ypc: number | null;
  success_rate: number | null;  // 0-1
  epa_per_att: number | null;
  lg_avg_epa_per_att: number | null;
}

export interface DashRbChip {
  value: number;
  pct: number; // 0-100 percentile rank within the eligible pool
}

export interface DashRbLanesHeader {
  mtf_per_att: DashRbChip | null;
  yac_per_att: DashRbChip | null;
  explosive_rate: DashRbChip | null;
  breakaway_pct: DashRbChip | null;
  success_rate: DashRbChip | null;
}

export interface DashRbLanes {
  player_id: string;
  full_name: string | null;
  position: string | null;
  season: number;
  eligible: boolean;
  reason?: string;
  lanes?: DashRbLane[];
  header?: DashRbLanesHeader;
  carries?: number;
  min_carries?: number;
}

export function dashboardRbLanes(
  playerId: string,
  season: number,
): Promise<DashRbLanes> {
  const u = new URLSearchParams({ player_id: playerId, season: String(season) });
  return getJSON<DashRbLanes>(`${BASE}/api/dashboard/rb-lanes?${u}`);
}

// ── IDP alignment (Player Profile Sections Phase 3) ─────────────────────────
export interface DashAlignmentSeg {
  bucket: 'dl' | 'box' | 'slot' | 'corner' | 'fs';
  snaps: number;
  share: number; // 0-1
}

export interface DashRoleSeg {
  bucket: 'run_defense' | 'pass_rush' | 'coverage';
  snaps: number;
  share: number; // 0-1
}

export interface DashIdpChip {
  value: number;
  pct: number; // 0-100 percentile rank within the eligible pool (pre-inverted server-side for lower-is-better metrics)
}

export interface DashIdpHeader {
  tackle_opp_rate: DashIdpChip | null;
  missed_tackle_rate: DashIdpChip | null;
  pressure_rate: DashIdpChip | null;
  coverage_eff: DashIdpChip | null;
  fp_per_snap: DashIdpChip | null;
}

export interface DashIdpAlignment {
  player_id: string;
  full_name: string | null;
  position: string | null;
  season: number;
  eligible: boolean;
  reason?: string;
  alignment?: DashAlignmentSeg[];
  role?: DashRoleSeg[];
  header?: DashIdpHeader;
  total_snaps?: number;
  min_snaps?: number;
  position_group?: 'DE' | 'DT' | 'LB' | 'CB' | 'S';
}

export function dashboardIdpAlignment(
  playerId: string,
  season: number,
  leagueId?: string | null,
): Promise<DashIdpAlignment> {
  const params: Record<string, string> = { player_id: playerId, season: String(season) };
  if (leagueId && leagueId !== 'default') params.league_id = leagueId;
  const u = new URLSearchParams(params);
  return getJSON<DashIdpAlignment>(`${BASE}/api/dashboard/idp-alignment?${u}`);
}
