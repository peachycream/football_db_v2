// Mirrors GET /gameday/live's response contract (GAMEDAY_TRACKER_BUILD.md #3).

export type GameState = 'pre' | 'in' | 'post' | 'bye';

export interface GamedayPlayer {
  name: string;
  nfl_team: string | null;
  slot: string;
  points: number;
  game_state: GameState;
  period: number | null;
  clock: string | null;
  /** Off-by-default "projected finish" polish (Phase 3). Approximate --
   *  MFL's own projectedScores for MFL leagues, Sleeper's generic PPR
   *  projections (not this league's actual custom scoring) for Sleeper
   *  leagues. null when unavailable for that player/week. */
  projected_points: number | null;
}

export interface GamedaySide {
  entry_id: string | number;
  name: string;
  score: number;
  starters_total: number;
  starters_yet_to_play: number;
  starters_in_play: number;
  starters_done: number;
  players: GamedayPlayer[];
}

export type MatchupType = 'h2h' | 'pool' | 'bracket';

export interface GamedayMatchup {
  type: MatchupType;
  pool_rank: number | null;
  me: GamedaySide;
  opponent: GamedaySide | null;
}

export interface GamedayLeague {
  league_id: string;
  source: 'mfl' | 'sleeper';
  name: string;
  structure: MatchupType;
  my_entry_id: string | number;
  matchups: GamedayMatchup[];
}

export interface GamedayError {
  league_id: string;
  source: string;
  message: string;
}

export interface GamedayResponse {
  /** Offseason pause: server short-circuited before paused_until, leagues is
   *  empty and season/week are null. Widgets render nothing. */
  paused?: boolean;
  paused_until?: string;
  generated_at: string;
  cache_age_seconds: number;
  /** null only on a paused response */
  season: number | null;
  week: number | null;
  replay: boolean;
  any_live: boolean;
  leagues: GamedayLeague[];
  errors: GamedayError[];
}
