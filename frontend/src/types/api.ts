// API types matching viz_explorer.py blueprint contracts.

export type Granularity = 'season' | 'week' | 'career';

export type ValueType = 'continuous' | 'categorical';

export interface StatMeta {
  stat_id: string;
  label: string;
  source_table: string;
  source_column: string;
  positions: string[];
  agg_method: 'sum' | 'avg' | 'weighted_avg' | 'first';
  weight_column: string | null;
  value_type: ValueType;
  threshold_default: number | null;
  threshold_column: string | null;
  format_str: string | null;
  source_group: string;
  description: string | null;
  /** Computed server-side from the table's own columns (week+season+team
   *  present) -- the same criterion the query builder enforces for the
   *  personnel filter, so this can never drift from what actually works. */
  is_weekly_source: boolean;
}

export interface RegistryResponse {
  stats: StatMeta[];
  count: number;
}

// season -> list of available seasons. null = table is not season-scoped.
export interface SeasonsResponse {
  by_table: Record<string, number[] | null>;
}

export interface Dot {
  player_id: string;
  name: string;
  pos: string | null;
  team: string | null;
  /** Number in season/week mode, string label like 'Career' or '2018-2025' in career mode. */
  season: number | string | null;
  x: number | null;
  y: number | null;
  color: number | string | null;
  size: number | null;
}

export interface QueryConfig {
  granularity: Granularity;
  seasons: number[];
  week?: number | null;
  positions: string[];
  teams: string[];
  x_stat: string | null;
  y_stat: string | null;
  color_stat: string | null;
  size_stat: string | null;
  min_threshold: number | null;
  personnel_group: string | null;   // '10' | '11' | '12' | '13' | '20' | '21' | '22' | '23' | null
  personnel_min_pct: number | null; // 0-100; null = no personnel filter
}

export interface QueryResponse {
  dots: Dot[];
  warnings: string[];
  x_meta: StatMeta;
  y_meta: StatMeta;
  color_meta: StatMeta | null;
  size_meta: StatMeta | null;
  row_count: number;
  capped: boolean;
}

export interface QueryError {
  error: string;
  detail?: string;
}

// ───────────────────────────────────────────────────────────────────────────
// Similar-player search (chunk 7 / Open Item #10)
// ───────────────────────────────────────────────────────────────────────────

export interface SimilarRequest {
  player_id: string;
  config: QueryConfig;
  n?: number;
}

export interface SimilarAnchor {
  player_id: string;
  name: string;
  x: number;
  y: number;
  season: number | string | null;
}

export interface SimilarRow {
  player_id: string;
  name: string;
  pos: string | null;
  team: string | null;
  season: number | string | null;
  x: number;
  y: number;
  distance: number;
}

export interface SimilarResponse {
  anchor: SimilarAnchor;
  similar: SimilarRow[];
  warnings: string[];
}

// ───────────────────────────────────────────────────────────────────────────
// Saved views (chunk 5)
// ───────────────────────────────────────────────────────────────────────────

/**
 * The shape we persist as `config_json` server-side. It's everything from
 * AppState EXCEPT highlights (those are a "watch list" per the chunk-3
 * design decision and not tied to a particular saved view).
 */
export interface SavedViewState {
  config: QueryConfig;
  showQuadrants: boolean;
  /** Added after the first saved views were written, so views persisted
   *  before it will not carry the key — readers must default it to false
   *  (see App.tsx handleViewLoad) rather than trusting it to be present. */
  showLabels: boolean;
  trendline: 'off' | 'global' | 'per_group';
}

/** What the list endpoint returns — no config body. */
export interface SavedViewSummary {
  view_id: number;
  name: string;
  description: string | null;
  created_at: string;          // SQL TIMESTAMP, e.g. "2025-05-25 12:32:23"
  last_used: string | null;
}

/** What the single-view endpoint returns — summary + parsed config. */
export interface SavedView extends SavedViewSummary {
  config: SavedViewState | null;
  /** If config_json failed to parse, the raw text is returned for recovery. */
  config_raw?: string;
}

export interface ListViewsResponse {
  views: SavedViewSummary[];
}

// ───────────────────────────────────────────────────────────────────────────
// AI chat (chunk 6)
// ───────────────────────────────────────────────────────────────────────────

/**
 * A suggestion is a chart config the assistant proposes. Two kinds:
 *   - 'config'    → single proposal from suggest_config
 *   - 'view_set'  → one card from a suggest_multiple_configs batch
 * The kind is currently informational; the frontend renders both the same way.
 */
export type ChatSuggestionKind = 'config' | 'view_set';

export interface ChatSuggestion {
  kind: ChatSuggestionKind;
  label: string;
  description: string;
  /**
   * Backend-validated to reference only real stat_ids in the registry; safe to
   * pass to the load_view reducer action. Not all fields may be present — the
   * backend may emit a partial config and the frontend fills in defaults
   * (e.g. teams=[] if missing).
   */
  config: Partial<QueryConfig>;
}

/**
 * Display-ready messages returned by GET /chat/<id>. The backend flattens raw
 * Anthropic message blocks into a UI-friendly shape:
 *   - user messages collapse to a single text string
 *   - assistant messages keep block order so suggestion cards render inline
 *     at the position the tool was called
 *   - tool_result "user" messages and standalone tool_use blocks are dropped
 */
export type ChatBlock =
  | { type: 'text'; text: string }
  | { type: 'suggestion'; suggestion: ChatSuggestion };

export type ChatDisplayMessage =
  | { role: 'user'; text: string }
  | { role: 'assistant'; blocks: ChatBlock[] };

export interface ChatNewResponse {
  conversation_id: string;
}

export interface ChatLoadResponse {
  conversation_id: string;
  messages: ChatDisplayMessage[];
}

export interface ChatSendRequest {
  message: string;
  /** Omit on first turn — server returns a new uuid in the response. */
  conversation_id?: string;
  current_config?: Partial<QueryConfig>;
  current_dot_count?: number;
}

export interface ChatTrace {
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ChatSendResponse {
  conversation_id: string;
  /** Concatenated text from final assistant turn. */
  reply: string;
  /** Post-validation; may be empty. */
  suggestions: ChatSuggestion[];
  /** Dropped suggestions, model warnings, etc. */
  warnings: string[];
  trace: ChatTrace;
}

export interface ChatDeleteResponse {
  ok: true;
  conversation_id: string;
}
