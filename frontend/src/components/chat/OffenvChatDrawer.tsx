import { useCallback, useEffect, useRef, useState } from 'react';
import type { OffenvChatDisplayMessage, OffenvChatSendResponse } from '@/lib/offenvChatApi';
import { offenvChatSend, offenvChatClear } from '@/lib/offenvChatApi';
import type { TeamOffenseEnvResponse } from '@/lib/offenvApi';
import { cn } from '@/lib/utils';
import { ChatInput } from './ChatInput';

interface OffenvChatDrawerProps {
  open: boolean;
  onClose: () => void;
  /** The dashboard response currently on screen -- sent with each turn as
   *  primary context. The model can also reach for a query_database tool
   *  (NL-to-SQL, read-only) for anything this payload doesn't cover. */
  dashboardData: TeamOffenseEnvResponse | null;
}

const CONVO_ID_KEY = 'offenv.chat.conversationId';

/**
 * Chat drawer for the Team Offense dashboard. Simpler sibling of viz's
 * ChatDrawer -- no suggestion cards, fixed-position overlay (this page isn't
 * a flex-row layout like the Scatter Explorer, so a slide-in overlay matches
 * the page shell better than a flex sibling -- same pattern as the game-day
 * tracker's drawer). Does share the tool-loop status pattern (liveStatus)
 * now that the backend has a query_database tool.
 */
export function OffenvChatDrawer({ open, onClose, dashboardData }: OffenvChatDrawerProps) {
  const [conversationId, setConversationId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(CONVO_ID_KEY);
    } catch {
      return null;
    }
  });
  const [messages, setMessages] = useState<OffenvChatDisplayMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState('');
  /** Real progress text from the in-flight stream (tool_use start events). */
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      if (conversationId) localStorage.setItem(CONVO_ID_KEY, conversationId);
      else localStorage.removeItem(CONVO_ID_KEY);
    } catch {
      // localStorage unavailable -- fine.
    }
  }, [conversationId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, sending, streamingText]);

  const handleSend = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending || !dashboardData) return;

    setMessages((prev) => [...prev, { role: 'user', text }]);
    setDraft('');
    setSending(true);
    setError(null);
    setStreamingText('');
    setLiveStatus(null);

    try {
      const resp: OffenvChatSendResponse = await offenvChatSend(
        {
          message: text,
          conversation_id: conversationId ?? undefined,
          dashboard_data: dashboardData,
        },
        {
          onStatus: (t) => setLiveStatus(t),
          onTextDelta: (t) => setStreamingText((prev) => prev + t),
        },
      );

      if (resp.conversation_id !== conversationId) {
        setConversationId(resp.conversation_id);
      }

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          blocks: resp.reply ? [{ type: 'text', text: resp.reply }] : [],
          queries: resp.queries?.length ? resp.queries : undefined,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
      setStreamingText('');
      setLiveStatus(null);
    }
  }, [draft, sending, conversationId, dashboardData]);

  const handleClear = useCallback(async () => {
    setError(null);
    setMessages([]);
    if (conversationId) {
      try {
        await offenvChatClear(conversationId);
      } catch (e) {
        console.warn('offenvChatClear failed:', e);
      }
    }
    setConversationId(null);
  }, [conversationId]);

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} aria-hidden="true" />
      )}
      <aside
        aria-label="Dashboard chat assistant"
        aria-hidden={!open}
        className={cn(
          'fixed top-0 right-0 z-50 h-full w-full sm:w-[380px] border-l border-border bg-bg-card',
          'flex flex-col transition-transform duration-200 ease-out',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <div className="h-12 shrink-0 border-b border-border px-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">Ask about this dashboard</h2>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleClear}
              disabled={messages.length === 0 && !conversationId}
              className="h-7 px-2 rounded-md text-xs text-text-muted hover:text-text hover:bg-bg-elevated
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Clear conversation"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={onClose}
              className="h-7 w-7 rounded-md inline-flex items-center justify-center
                         text-text-muted hover:text-text hover:bg-bg-elevated transition-colors text-base"
              aria-label="Close chat"
            >
              ×
            </button>
          </div>
        </div>

        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
          {messages.length === 0 && !sending && <EmptyState />}

          {messages.map((m, i) => (
            <MessageRow key={i} message={m} />
          ))}

          {sending && (
            streamingText ? (
              <div className="text-sm text-text whitespace-pre-wrap">
                {streamingText}
                <span className="inline-block w-1.5 h-3 bg-text-dim/60 ml-0.5 align-text-bottom animate-pulse" />
              </div>
            ) : (
              <ThinkingDots status={liveStatus} />
            )
          )}

          {error && (
            <div className="text-xs text-error border border-error/30 rounded-md p-2 bg-error/5">
              <div className="font-medium mb-0.5">Request failed</div>
              <div className="text-[11px] opacity-90">{error}</div>
            </div>
          )}
        </div>

        <ChatInput
          value={draft}
          onChange={setDraft}
          onSend={handleSend}
          disabled={sending || !dashboardData}
          placeholder="Ask about the data on screen…"
        />
      </aside>
    </>
  );
}

function MessageRow({ message }: { message: OffenvChatDisplayMessage }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-md bg-accent/15 text-text px-2.5 py-1.5 text-sm whitespace-pre-wrap break-words">
          {message.text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {message.blocks.map((b, i) => (
        <div key={i} className="text-sm text-text whitespace-pre-wrap">
          {b.text}
        </div>
      ))}
      {message.queries && message.queries.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-text-dim hover:text-text-muted select-none">
            {message.queries.length === 1 ? 'View SQL' : `View SQL (${message.queries.length} queries)`}
          </summary>
          <div className="mt-1 space-y-1">
            {message.queries.map((q, i) => (
              <pre
                key={i}
                className="whitespace-pre-wrap break-words rounded-md border border-border bg-bg-elevated p-2 text-[11px] text-text-muted"
              >
                {q.sql}
              </pre>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-4">
      <p className="text-sm text-text-muted">Ask about the team, splits, or trends shown here.</p>
      <div className="text-xs text-text-dim mt-2 space-y-0.5">
        <div>"Why is their pace percentile so high?"</div>
        <div>"How does their neutral-script EPA compare to the league?"</div>
        <div>"How did this compare to their 2023 season?"</div>
      </div>
    </div>
  );
}

function ThinkingDots({ status }: { status?: string | null }) {
  return (
    <div className="flex items-center gap-1.5 text-text-dim text-xs">
      <span className="inline-flex gap-0.5">
        <Dot delay="0ms" />
        <Dot delay="150ms" />
        <Dot delay="300ms" />
      </span>
      {status && <span>{status}</span>}
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="inline-block h-1 w-1 rounded-full bg-text-dim animate-pulse"
      style={{ animationDelay: delay }}
    />
  );
}
