// draftApi.ts -- typed client for the Phase 3 / 3.5 draft-board endpoints
// (DRAFT_BOARD_BUILD_v3.md). All reads are server-side-cached by the poller;
// the browser never touches MFL directly.

export const DRAFT_LEAGUES = [
  { id: '30590', name: 'TINO NFL Elite', short: 'TINO Elite' },
  { id: '57653', name: 'TNT Devy', short: 'TNT Devy' },
  { id: '60398', name: 'TINO March Madness', short: 'March Madness' },
  { id: '60856', name: 'TINO NCAA', short: 'TINO NCAA' },
  { id: '55757', name: 'TWE', short: 'TWE' },
] as const;

export type Band = 'rookie' | 'fa' | 'devy';

export interface DraftPick {
  overall_pick: number;
  round: number;
  pick_in_round: number;
  franchise_id: string;
  mfl_player_id: string | null;
  player_id: string | null;
  picked_at: string | null;
  /** Display name for a made pick. Devy slots fall back to "devy slot #0803"
   *  until the owner renames the placeholder in MFL (Blocker E / D10). */
  player_name?: string | null;
  /** True while a devy slot is picked but not yet renamed by its owner. */
  devy_pending?: boolean;
}

export interface DraftState {
  ok: boolean;
  league: string;
  unit: string;
  picks_made: number;
  total_slots: number;
  on_clock: string | null;
  on_clock_overall: number | null;
  turon_franchise: string | null;
  turon_next_overall: number | null;
  turon_queue_position: number | null;
  last_10_picks: DraftPick[];
  draft_complete: boolean;
}

export interface BoardPlayer {
  player_id: string;
  pool_band: Band;
  resolution_status: 'resolved' | 'synthetic';
  adp: number | null;
  proj_value: number | null;
  proj_rank: number | null;
  mock_rank: number | null;
  draft_class: number | null;
  war_value: number | null;
  composite_rank: number | null;
  full_name: string | null;
  position: string | null;
  team_current: string | null;
  tier: number | null;
  note: string | null;
  cfb_prior: Record<string, any> | null;
}

export interface BoardResponse {
  ok: boolean;
  league: string;
  band: string | null;
  count: number;
  players: BoardPlayer[];
  unavailable_count: number;
}

export interface HoleRow {
  position: string;
  required_min: number;
  rostered: number;
  hole: number;
}

export interface RosterResponse {
  ok: boolean;
  league: string;
  franchise: string;
  rostered_count: number;
  position_counts: Record<string, number>;
  hole_map: HoleRow[];
}

export interface ScarcityResponse {
  ok: boolean;
  league: string;
  scarcity: Record<string, Record<string, number>>;
}

export interface PredictPick {
  overall_pick: number;
  round: number;
  franchise: string;
  probabilities: Record<string, number>;
  top_positions: string[];
  prob_sum: number;
  tendency_flat: boolean;
  tendency_matched_drafts: number;
}

export interface PredictResponse {
  ok: boolean;
  league: string;
  estimate: boolean;
  next_picks: PredictPick[];
}

export interface SurvivalResponse {
  ok: boolean;
  league: string;
  player_id: string;
  available_now?: boolean;
  position?: string;
  rank_within_position?: number;
  picks_until?: number;
  survival?: number;
  survival_pct_rounded?: number;
  estimate: boolean;
  error?: string;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : '';
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const isMock = () =>
  new URLSearchParams(window.location.search).get('mock') === '1';

const mockFlag = () => (isMock() ? { mock: 1 } : {});

export const fetchDraftState = (league: string) =>
  get<DraftState>(`/api/draft/state${qs({ league, ...mockFlag() })}`);

export const fetchBoard = (league: string, band?: string, pos?: string, limit = 300) =>
  get<BoardResponse>(`/api/draft/board${qs({ league, band, pos, limit, ...mockFlag() })}`);

export const fetchRoster = (league: string) =>
  get<RosterResponse>(`/api/draft/roster${qs({ league, ...mockFlag() })}`);

export const fetchScarcity = (league: string) =>
  get<ScarcityResponse>(`/api/draft/scarcity${qs({ league, ...mockFlag() })}`);

export const fetchPredict = (league: string, n = 3) =>
  get<PredictResponse>(`/api/draft/predict${qs({ league, n, ...mockFlag() })}`);

export const fetchSurvival = (league: string, playerId: string) =>
  get<SurvivalResponse>(`/api/draft/survival${qs({ league, player_id: playerId, ...mockFlag() })}`);

export async function saveTier(
  league: string,
  playerId: string,
  tier: number | null,
  note: string | null,
): Promise<{ ok: boolean }> {
  const r = await fetch('/api/draft/tier', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ league, player_id: playerId, tier, note }),
  });
  if (!r.ok) throw new Error(`tier save -> HTTP ${r.status}`);
  return await r.json();
}
