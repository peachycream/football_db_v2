import type { GamedayLeague, GamedayMatchup, GamedayResponse, GamedaySide } from '@/types/gameday';

export interface FlatMatchup {
  key: string;
  league: GamedayLeague;
  matchup: GamedayMatchup;
}

export function flattenMatchups(data: GamedayResponse | null): FlatMatchup[] {
  if (!data) return [];
  const out: FlatMatchup[] = [];
  for (const league of data.leagues) {
    league.matchups.forEach((matchup, i) => {
      out.push({ key: `${league.league_id}:${i}`, league, matchup });
    });
  }
  return out;
}

export function sideIsLive(side: GamedaySide | null): boolean {
  if (!side) return false;
  return side.players.some((p) => p.game_state === 'in');
}

export function matchupIsLive(m: GamedayMatchup): boolean {
  return sideIsLive(m.me) || sideIsLive(m.opponent);
}

// Live matchups first, otherwise stable (league registration order).
export function sortForTicker(flats: FlatMatchup[]): FlatMatchup[] {
  return [...flats].sort((a, b) => {
    const la = matchupIsLive(a.matchup) ? 0 : 1;
    const lb = matchupIsLive(b.matchup) ? 0 : 1;
    return la - lb;
  });
}

export function fmtScore(n: number): string {
  return n.toFixed(1);
}

export function chipLabel(m: GamedayMatchup): string {
  if (m.opponent) {
    return `${m.me.name} ${fmtScore(m.me.score)} – ${fmtScore(m.opponent.score)} ${m.opponent.name}`;
  }
  if (m.pool_rank != null) {
    return `${m.me.name} ${fmtScore(m.me.score)} · pool #${m.pool_rank}`;
  }
  return `${m.me.name} ${fmtScore(m.me.score)}`;
}

export function yetToPlayLabel(m: GamedayMatchup): string | null {
  const yet = m.me.starters_yet_to_play + (m.opponent?.starters_yet_to_play ?? 0);
  if (yet <= 0) return null;
  return `${yet} yet to play`;
}

export const GAME_STATE_LABEL: Record<string, string> = {
  pre: 'Pre',
  in: 'Live',
  post: 'Final',
  bye: 'Bye',
};

// Every side's players share one game_state -- summarize a matchup as
// live/final/pre for a compact ticker-chip badge.
export function matchupStateLabel(m: GamedayMatchup): 'LIVE' | 'FINAL' | 'PRE' | null {
  const all = [...m.me.players, ...(m.opponent?.players ?? [])];
  if (all.length === 0) return null;
  if (all.some((p) => p.game_state === 'in')) return 'LIVE';
  if (all.every((p) => p.game_state === 'post' || p.game_state === 'bye')) return 'FINAL';
  if (all.every((p) => p.game_state === 'pre')) return 'PRE';
  return null; // mixed pre/post with none live -- ambiguous, skip the badge
}

// Smallest score margin among my currently-live H2H matchups. Pure
// client-side, no backend/token cost (Phase 3 "closest matchup" polish).
export function closestLiveMatchupKey(flats: FlatMatchup[]): string | null {
  let best: { key: string; margin: number } | null = null;
  for (const f of flats) {
    if (!f.matchup.opponent || !matchupIsLive(f.matchup)) continue;
    const margin = Math.abs(f.matchup.me.score - f.matchup.opponent.score);
    if (best === null || margin < best.margin) best = { key: f.key, margin };
  }
  return best?.key ?? null;
}

// 30s live / 300s idle backend TTLs -- if the served blob is much older
// than that, the backend is likely stuck re-polling a throttled/failing
// source. errors[] non-empty is the more direct signal; cache age is a
// fallback for "everything technically 200'd but nothing is fresh."
export function isStale(data: GamedayResponse | null): boolean {
  if (!data) return false;
  if (data.errors.length > 0) return true;
  const threshold = data.any_live ? 90 : 600;
  return data.cache_age_seconds > threshold;
}
