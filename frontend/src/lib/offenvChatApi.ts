// Chat client for the Team Offensive Environment Dashboard. Deliberately not
// shared with the Scatter Explorer's chat (lib/api.ts chatSend/etc.) -- no
// suggestion cards, the request carries the currently-fetched dashboard JSON
// as context instead of a query config. The backend has a query_database
// tool (NL-to-SQL, read-only) for questions the dashboard JSON can't answer;
// `onStatus` surfaces "Querying the database…" while that's in flight, same
// pattern as the Scatter Explorer's tool-use status frames. Mirrors
// app/offenv_chat.py's contract.
import type { TeamOffenseEnvResponse } from './offenvApi';

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

export type OffenvChatDisplayMessage =
  | { role: 'user'; text: string }
  | { role: 'assistant'; blocks: { type: 'text'; text: string }[]; queries?: { sql: string }[] };

export interface OffenvChatNewResponse {
  conversation_id: string;
}

export interface OffenvChatLoadResponse {
  conversation_id: string;
  messages: OffenvChatDisplayMessage[];
}

export interface OffenvChatSendRequest {
  message: string;
  conversation_id?: string;
  dashboard_data: TeamOffenseEnvResponse;
}

export interface OffenvChatSendResponse {
  conversation_id: string;
  reply: string;
  /** SQL statements the model ran via query_database this turn, if any --
   *  surfaced for transparency (same "View SQL" idea as the main NL-to-SQL page). */
  queries: { sql: string }[];
  trace: { input_tokens: number; output_tokens: number; tool_calls: number };
}

export interface OffenvChatDeleteResponse {
  ok: true;
  conversation_id: string;
}

export function offenvChatNew(): Promise<OffenvChatNewResponse> {
  return jsonFetch<OffenvChatNewResponse>(`${BASE}/api/team-offense-env/chat/new`, {
    method: 'POST',
  });
}

export function offenvChatLoad(conversationId: string): Promise<OffenvChatLoadResponse> {
  return jsonFetch<OffenvChatLoadResponse>(
    `${BASE}/api/team-offense-env/chat/${encodeURIComponent(conversationId)}`,
  );
}

export interface OffenvChatStreamHandlers {
  /** A tool_use block started streaming in -- real progress, e.g. "Querying the database…". */
  onStatus?: (text: string) => void;
  onTextDelta?: (text: string) => void;
}

export async function offenvChatSend(
  req: OffenvChatSendRequest,
  handlers: OffenvChatStreamHandlers = {},
): Promise<OffenvChatSendResponse> {
  const res = await fetch(`${BASE}/api/team-offense-env/chat`, {
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
  let result: OffenvChatSendResponse | null = null;

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
        result = payload as OffenvChatSendResponse;
      }
    }
  }

  if (!result) {
    throw new Error('Chat stream ended without a final response.');
  }
  return result;
}

export function offenvChatClear(conversationId: string): Promise<OffenvChatDeleteResponse> {
  return jsonFetch<OffenvChatDeleteResponse>(
    `${BASE}/api/team-offense-env/chat/${encodeURIComponent(conversationId)}`,
    { method: 'DELETE' },
  );
}
