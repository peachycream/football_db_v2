import { useCallback, useEffect, useRef, useState } from 'react';
import type { DefenvChatDisplayMessage, DefenvChatSendResponse } from '@/lib/defenvChatApi';
import { defenvChatSend, defenvChatClear } from '@/lib/defenvChatApi';
import type { TeamDefenseEnvResponse } from '@/lib/defenvApi';
import { cn } from '@/lib/utils';
import { ChatInput } from './ChatInput';

interface DefenvChatDrawerProps {
  open: boolean;
  onClose: () => void;
  /** The dashboard response currently on screen -- sent with each turn as
   *  the model's entire data source (no tools, no DB access on its own). */
  dashboardData: TeamDefenseEnvResponse | null;
}

const CONVO_ID_KEY = 'defenv.chat.conversationId';

/**
 * "Explain what's on screen" chat drawer for the Team Defense dashboard.
 * Byte-for-byte mirror of OffenvChatDrawer.tsx's structure -- Phase 4's
 * mirror of the offense chat, NOT the Phase 5 NL-to-SQL replacement (see
 * DEF_ENV_LOG.md Gate 0 finding: the offense page's own chat has no DB
 * access either, so this is genuine parity, not a placeholder).
 */
export function DefenvChatDrawer({ open, onClose, dashboardData }: DefenvChatDrawerProps) {
  const [conversationId, setConversationId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(CONVO_ID_KEY);
    } catch {
      return null;
    }
  });
  const [messages, setMessages] = useState<DefenvChatDisplayMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState('');

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

    try {
      const resp: DefenvChatSendResponse = await defenvChatSend(
        {
          message: text,
          conversation_id: conversationId ?? undefined,
          dashboard_data: dashboardData,
        },
        { onTextDelta: (t) => setStreamingText((prev) => prev + t) },
      );

      if (resp.conversation_id !== conversationId) {
        setConversationId(resp.conversation_id);
      }

      setMessages((prev) => [
        ...prev,
        { role: 'assistant', blocks: resp.reply ? [{ type: 'text', text: resp.reply }] : [] },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
      setStreamingText('');
    }
  }, [draft, sending, conversationId, dashboardData]);

  const handleClear = useCallback(async () => {
    setError(null);
    setMessages([]);
    if (conversationId) {
      try {
        await defenvChatClear(conversationId);
      } catch (e) {
        console.warn('defenvChatClear failed:', e);
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
              <ThinkingDots />
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

function MessageRow({ message }: { message: DefenvChatDisplayMessage }) {
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
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-4">
      <p className="text-sm text-text-muted">Ask about the team's defense, sections, or trends shown here.</p>
      <div className="text-xs text-text-dim mt-2 space-y-0.5">
        <div>"Why is their havoc rate percentile so low?"</div>
        <div>"How does their pass rush compare to the league?"</div>
        <div>"What does the coverage shell breakdown tell us?"</div>
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5 text-text-dim text-xs">
      <span className="inline-flex gap-0.5">
        <Dot delay="0ms" />
        <Dot delay="150ms" />
        <Dot delay="300ms" />
      </span>
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
