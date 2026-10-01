import type {
  RegistryResponse,
  SeasonsResponse,
  QueryConfig,
  QueryResponse,
  QueryError,
  SimilarRequest,
  SimilarResponse,
  ListViewsResponse,
  SavedView,
  SavedViewState,
  ChatNewResponse,
  ChatLoadResponse,
  ChatSendRequest,
  ChatSendResponse,
  ChatDeleteResponse,
} from '@/types/api';

// In dev, Vite proxies /api -> Flask on :5000.
// In prod, Flask serves both /viz and /api so relative paths work.
const BASE = '';

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.error || body.detail || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function fetchRegistry(): Promise<RegistryResponse> {
  return jsonFetch<RegistryResponse>(`${BASE}/api/viz/registry`);
}

export function fetchSeasons(): Promise<SeasonsResponse> {
  return jsonFetch<SeasonsResponse>(`${BASE}/api/viz/seasons`);
}

export function runQuery(cfg: QueryConfig): Promise<QueryResponse> {
  return jsonFetch<QueryResponse>(`${BASE}/api/viz/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  });
}

// Helper used by callers to surface server-side error detail
export function isQueryError(x: unknown): x is QueryError {
  return typeof x === 'object' && x != null && 'error' in x;
}

// ───────────────────────────────────────────────────────────────────────────
// Similar-player search (chunk 7 / Open Item #10)
// ───────────────────────────────────────────────────────────────────────────

export function findSimilar(req: SimilarRequest): Promise<SimilarResponse> {
  return jsonFetch<SimilarResponse>(`${BASE}/api/viz/similar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

// ───────────────────────────────────────────────────────────────────────────
// Saved views (chunk 5) — uses the same jsonFetch helper for uniform error
// handling. All five endpoints live under /api/viz/views.
// ───────────────────────────────────────────────────────────────────────────

export function listViews(): Promise<ListViewsResponse> {
  return jsonFetch<ListViewsResponse>(`${BASE}/api/viz/views`);
}

export function getView(viewId: number): Promise<SavedView> {
  return jsonFetch<SavedView>(`${BASE}/api/viz/views/${viewId}`);
}

export function createView(payload: {
  name: string;
  description?: string | null;
  config: SavedViewState;
}): Promise<SavedView> {
  return jsonFetch<SavedView>(`${BASE}/api/viz/views`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function updateView(
  viewId: number,
  payload: {
    name?: string;
    description?: string | null;
    config?: SavedViewState;
  },
): Promise<SavedView> {
  return jsonFetch<SavedView>(`${BASE}/api/viz/views/${viewId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function deleteView(viewId: number): Promise<{ deleted: number }> {
  return jsonFetch<{ deleted: number }>(`${BASE}/api/viz/views/${viewId}`, {
    method: 'DELETE',
  });
}

export function touchView(viewId: number): Promise<{ view_id: number; touched: boolean }> {
  return jsonFetch<{ view_id: number; touched: boolean }>(
    `${BASE}/api/viz/views/${viewId}/touch`,
    { method: 'POST' },
  );
}

// ───────────────────────────────────────────────────────────────────────────
// AI chat (chunk 6) — four endpoints under /api/viz/chat. All use jsonFetch
// so the drawer can catch thrown Errors and surface err.message directly.
// ───────────────────────────────────────────────────────────────────────────

/**
 * Allocate a fresh conversation_id. No DB write happens server-side until the
 * first message is sent — calling this and never sending is free.
 */
export function chatNew(): Promise<ChatNewResponse> {
  return jsonFetch<ChatNewResponse>(`${BASE}/api/viz/chat/new`, {
    method: 'POST',
  });
}

/**
 * Load full display-ready history for a conversation. Used when reopening the
 * drawer mid-session or restoring from localStorage on page refresh.
 * Throws on 404 (unknown conversation_id) — callers should handle by minting
 * a new conversation via chatNew().
 */
export function chatLoad(conversationId: string): Promise<ChatLoadResponse> {
  return jsonFetch<ChatLoadResponse>(
    `${BASE}/api/viz/chat/${encodeURIComponent(conversationId)}`,
  );
}

export interface ChatStreamHandlers {
  /** A tool_use block started streaming in — real progress, e.g. "Searching the stat registry…". */
  onStatus?: (text: string) => void;
  /** A chunk of the final prose reply, in generation order — append to build up the typed-out text. */
  onTextDelta?: (text: string) => void;
}

/**
 * Send a message; streams progress via Server-Sent Events and resolves with
 * the same shape the old one-shot endpoint returned once the `done` frame
 * arrives. Server runs the Opus tool loop (max 5 iterations, still
 * typically 3-10s total) — `handlers` surface real progress during that
 * wait instead of a static spinner. On the first turn, omit conversation_id
 * and use the one returned in the response for subsequent calls.
 */
export async function chatSend(
  req: ChatSendRequest,
  handlers: ChatStreamHandlers = {},
): Promise<ChatSendResponse> {
  const res = await fetch(`${BASE}/api/viz/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok || !res.body) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.error || body.detail || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let result: ChatSendResponse | null = null;

  while (true) {
    const { value, done: readerDone } = await reader.read();
    if (readerDone) break;
    buf += decoder.decode(value, { stream: true });

    let sepIdx;
    while ((sepIdx = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, sepIdx);
      buf = buf.slice(sepIdx + 2);
      const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
      if (!dataLine) continue;

      const payload = JSON.parse(dataLine.slice(6));
      if (payload.type === 'status') {
        handlers.onStatus?.(payload.text);
      } else if (payload.type === 'text_delta') {
        handlers.onTextDelta?.(payload.text);
      } else if (payload.type === 'error') {
        throw new Error(payload.error || 'Chat stream failed');
      } else if (payload.type === 'done') {
        result = payload as ChatSendResponse;
      }
    }
  }

  if (!result) {
    throw new Error('Chat stream ended without a final response.');
  }
  return result;
}

/**
 * Delete every message in a conversation. The conversation_id remains valid
 * to send into — the next message will start a fresh history under the same id.
 * Returns {ok:true, conversation_id} on success.
 */
export function chatClear(conversationId: string): Promise<ChatDeleteResponse> {
  return jsonFetch<ChatDeleteResponse>(
    `${BASE}/api/viz/chat/${encodeURIComponent(conversationId)}`,
    { method: 'DELETE' },
  );
}
