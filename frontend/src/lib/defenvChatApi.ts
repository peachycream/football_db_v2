// "Explain what's on screen" chat client for the Team Defense Environment
// Dashboard. Mirrors offenvChatApi.ts / app/team_def_env_chat.py's contract
// exactly -- no tool loop, no suggestion cards, the request carries the
// currently-fetched dashboard JSON as context instead of a query config.
import type { TeamDefenseEnvResponse } from './defenvApi';

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

export type DefenvChatDisplayMessage =
  | { role: 'user'; text: string }
  | { role: 'assistant'; blocks: { type: 'text'; text: string }[] };

export interface DefenvChatNewResponse {
  conversation_id: string;
}

export interface DefenvChatLoadResponse {
  conversation_id: string;
  messages: DefenvChatDisplayMessage[];
}

export interface DefenvChatSendRequest {
  message: string;
  conversation_id?: string;
  dashboard_data: TeamDefenseEnvResponse;
}

export interface DefenvChatSendResponse {
  conversation_id: string;
  reply: string;
  trace: { input_tokens: number; output_tokens: number };
}

export interface DefenvChatDeleteResponse {
  ok: true;
  conversation_id: string;
}

export function defenvChatNew(): Promise<DefenvChatNewResponse> {
  return jsonFetch<DefenvChatNewResponse>(`${BASE}/api/team-defense-env/chat/new`, {
    method: 'POST',
  });
}

export function defenvChatLoad(conversationId: string): Promise<DefenvChatLoadResponse> {
  return jsonFetch<DefenvChatLoadResponse>(
    `${BASE}/api/team-defense-env/chat/${encodeURIComponent(conversationId)}`,
  );
}

export interface DefenvChatStreamHandlers {
  onTextDelta?: (text: string) => void;
}

export async function defenvChatSend(
  req: DefenvChatSendRequest,
  handlers: DefenvChatStreamHandlers = {},
): Promise<DefenvChatSendResponse> {
  const res = await fetch(`${BASE}/api/team-defense-env/chat`, {
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
  let result: DefenvChatSendResponse | null = null;

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
      if (payload.type === 'text_delta') {
        handlers.onTextDelta?.(payload.text);
      } else if (payload.type === 'error') {
        throw new Error(payload.error || 'Chat stream failed');
      } else if (payload.type === 'done') {
        result = payload as DefenvChatSendResponse;
      }
    }
  }

  if (!result) {
    throw new Error('Chat stream ended without a final response.');
  }
  return result;
}

export function defenvChatClear(conversationId: string): Promise<DefenvChatDeleteResponse> {
  return jsonFetch<DefenvChatDeleteResponse>(
    `${BASE}/api/team-defense-env/chat/${encodeURIComponent(conversationId)}`,
    { method: 'DELETE' },
  );
}
