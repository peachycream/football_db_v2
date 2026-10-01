import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  ChatDisplayMessage,
  ChatSendResponse,
  QueryConfig,
} from '@/types/api';
import { chatSend, chatClear } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/primitives';
import { ChatInput } from './ChatInput';

interface ChatDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Snapshot of the current chart config — sent with each turn so the model
   *  can answer "modify this chart" questions. */
  currentConfig: QueryConfig;
  currentDotCount: number;
  /** Applies a suggestion's config onto the live chart (merges onto current
   *  config; owner decides how showQuadrants/trendline are preserved). */
  onApplySuggestion: (config: Partial<QueryConfig>) => void;
}

const CONVO_ID_KEY = 'viz.chat.conversationId';

/**
 * The chat drawer — owns conversation_id, message list, in-flight state.
 * Rendering of message contents:
 *   - user messages: plain text in a bubble
 *   - assistant messages: text as prose, suggestions as Apply/Dismiss cards
 */
export function ChatDrawer({
  open,
  onClose,
  currentConfig,
  currentDotCount,
  onApplySuggestion,
}: ChatDrawerProps) {
  // ─── State ────────────────────────────────────────────────────────────
  const [conversationId, setConversationId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(CONVO_ID_KEY);
    } catch {
      return null;
    }
  });
  const [messages, setMessages] = useState<ChatDisplayMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Holds the trace + warnings + suggestions of the last response so we can
   *  show the raw blob inline. Phase 4 swaps this for proper rendering. */
  const [lastResponse, setLastResponse] = useState<ChatSendResponse | null>(null);
  /** Keys ("messageIndex:blockIndex") of suggestion cards the user dismissed. */
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  /** Real progress text from the in-flight stream (tool_use start events) —
   *  replaces the old static "thinking…" label. */
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  /** Prose reply text as it streams in, token by token. */
  const [streamingText, setStreamingText] = useState('');

  const scrollRef = useRef<HTMLDivElement>(null);

  // ─── Effects ──────────────────────────────────────────────────────────

  // Persist conversation id so refreshes don't lose context.
  useEffect(() => {
    try {
      if (conversationId) localStorage.setItem(CONVO_ID_KEY, conversationId);
      else localStorage.removeItem(CONVO_ID_KEY);
    } catch {
      // localStorage unavailable — fine.
    }
  }, [conversationId]);

  // Scroll to bottom when messages or in-flight state change.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, sending, lastResponse, streamingText]);

  // ─── Actions ──────────────────────────────────────────────────────────

  const handleSend = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) return;

    // Optimistically render the user message
    setMessages((prev) => [...prev, { role: 'user', text }]);
    setDraft('');
    setSending(true);
    setError(null);
    setLiveStatus('Thinking…');
    setStreamingText('');

    try {
      const resp = await chatSend(
        {
          message: text,
          conversation_id: conversationId ?? undefined,
          current_config: currentConfig,
          current_dot_count: currentDotCount,
        },
        {
          onStatus: (t) => setLiveStatus(t),
          onTextDelta: (t) => setStreamingText((prev) => prev + t),
        },
      );

      // Lock in the conversation id (server may have minted it).
      if (resp.conversation_id !== conversationId) {
        setConversationId(resp.conversation_id);
      }

      // Build the assistant message's blocks from the response.
      const blocks: ChatDisplayMessage = {
        role: 'assistant',
        blocks: [
          ...(resp.reply ? [{ type: 'text' as const, text: resp.reply }] : []),
          ...resp.suggestions.map(
            (s) => ({ type: 'suggestion' as const, suggestion: s }),
          ),
        ],
      };
      setMessages((prev) => [...prev, blocks]);
      setLastResponse(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
      setLiveStatus(null);
      setStreamingText('');
    }
  }, [draft, sending, conversationId, currentConfig, currentDotCount]);

  const handleClear = useCallback(async () => {
    setError(null);
    setLastResponse(null);
    setMessages([]);
    if (conversationId) {
      try {
        await chatClear(conversationId);
      } catch (e) {
        // Non-fatal — local state is cleared regardless.
        console.warn('chatClear failed:', e);
      }
    }
    setConversationId(null);
  }, [conversationId]);

  // ─── Render ───────────────────────────────────────────────────────────

  return (
    <aside
      aria-label="Chat assistant"
      aria-hidden={!open}
      className={cn(
        'shrink-0 h-full border-l border-border bg-bg-card flex flex-col',
        'transition-[width] duration-200 ease-out',
        open ? 'w-[380px]' : 'w-0 overflow-hidden border-l-0',
      )}
    >
      {/* Drawer header */}
      <div className="h-12 shrink-0 border-b border-border px-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-text">Chat</h2>
          {sending && (
            <span className="text-[10px] uppercase tracking-wider text-text-dim truncate max-w-[200px]">
              {liveStatus ?? 'thinking…'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleClear}
            disabled={messages.length === 0 && !conversationId}
            className={cn(
              'h-7 px-2 rounded-md text-xs',
              'text-text-muted hover:text-text hover:bg-bg-elevated',
              'disabled:opacity-40 disabled:cursor-not-allowed',
              'transition-colors',
            )}
            title="Clear conversation"
          >
            Clear
          </button>
          <button
            type="button"
            onClick={onClose}
            className="h-7 w-7 rounded-md inline-flex items-center justify-center
                       text-text-muted hover:text-text hover:bg-bg-elevated
                       transition-colors text-base"
            aria-label="Close chat"
            title="Close"
          >
            ×
          </button>
        </div>
      </div>

      {/* Message scroll area */}
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3"
      >
        {messages.length === 0 && !sending && (
          <EmptyState />
        )}

        {messages.map((m, i) => (
          <MessageRow
            key={i}
            message={m}
            messageIndex={i}
            dismissed={dismissed}
            onApply={onApplySuggestion}
            onDismiss={(dismissKey) =>
              setDismissed((prev) => new Set(prev).add(dismissKey))
            }
          />
        ))}

        {sending && (
          streamingText ? (
            <div className="text-sm text-text whitespace-pre-wrap">
              {streamingText}
              <span className="inline-block w-1.5 h-3 bg-text-dim/60 ml-0.5 align-text-bottom animate-pulse" />
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <ThinkingDot />
              {liveStatus && (
                <span className="text-xs text-text-dim">{liveStatus}</span>
              )}
            </div>
          )
        )}

        {error && (
          <div className="text-xs text-error border border-error/30 rounded-md p-2 bg-error/5">
            <div className="font-medium mb-0.5">Request failed</div>
            <div className="text-[11px] opacity-90">{error}</div>
          </div>
        )}

        {/* Phase-3 raw response dump (will be removed in phase 4 once cards render properly) */}
        {lastResponse && (
          <details className="text-[10px] text-text-dim opacity-70">
            <summary className="cursor-pointer">last response (debug)</summary>
            <pre className="mt-1 p-2 bg-bg-elevated rounded overflow-x-auto whitespace-pre-wrap">
{JSON.stringify(
  {
    suggestions: lastResponse.suggestions.length,
    warnings: lastResponse.warnings,
    trace: lastResponse.trace,
  },
  null,
  2,
)}
            </pre>
          </details>
        )}
      </div>

      {/* Composer */}
      <ChatInput
        value={draft}
        onChange={setDraft}
        onSend={handleSend}
        disabled={sending}
      />
    </aside>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Message rendering
// ─────────────────────────────────────────────────────────────────────────

interface MessageRowProps {
  message: ChatDisplayMessage;
  messageIndex: number;
  dismissed: Set<string>;
  onApply: (config: Partial<QueryConfig>) => void;
  onDismiss: (key: string) => void;
}

function MessageRow({ message, messageIndex, dismissed, onApply, onDismiss }: MessageRowProps) {
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
      {message.blocks.map((b, i) => {
        if (b.type === 'text') {
          return (
            <div key={i} className="text-sm text-text whitespace-pre-wrap">
              {b.text}
            </div>
          );
        }
        const key = `${messageIndex}:${i}`;
        if (dismissed.has(key)) {
          return (
            <div key={i} className="text-[11px] text-text-dim italic px-0.5">
              Dismissed: {b.suggestion.label}
            </div>
          );
        }
        return (
          <div
            key={i}
            className="rounded-md border border-border bg-bg-elevated p-2 text-xs"
          >
            <div className="text-text font-medium">{b.suggestion.label}</div>
            <div className="text-text-muted mt-0.5">
              {b.suggestion.description}
            </div>
            <div className="flex items-center gap-1.5 mt-1.5">
              <Button
                variant="accent"
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => onApply(b.suggestion.config)}
              >
                Apply
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => onDismiss(key)}
              >
                Dismiss
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-4">
      <p className="text-sm text-text-muted">
        Ask the assistant about stats or chart ideas.
      </p>
      <div className="text-xs text-text-dim mt-2 space-y-0.5">
        <div>"Show WR YPRR vs target share for 2024"</div>
        <div>"What charts would help me draft a WR?"</div>
        <div>"Add PFF grade as color to this chart"</div>
      </div>
    </div>
  );
}

function ThinkingDot() {
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
