import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;          // true while a request is in flight
  placeholder?: string;
}

const MAX_CHARS = 2000;

/**
 * Composer at the bottom of the chat drawer. Auto-growing textarea, send on
 * Enter, newline on Shift+Enter. Char counter appears when nearing the cap.
 */
export function ChatInput({
  value,
  onChange,
  onSend,
  disabled,
  placeholder = 'Ask about stats or chart ideas…',
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize: grow up to ~8 lines, then scroll.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const trimmed = value.trim();
  const canSend = trimmed.length > 0 && !disabled;
  const charsLeft = MAX_CHARS - value.length;
  const showCounter = value.length > MAX_CHARS - 200;

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend) onSend();
    }
  }

  return (
    <div className="border-t border-border bg-bg-card p-2">
      <div
        className={cn(
          'flex items-end gap-2 rounded-md border border-border bg-bg-elevated',
          'focus-within:border-accent/50 focus-within:ring-1 focus-within:ring-accent/20',
          'transition-colors',
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            const next = e.target.value;
            if (next.length <= MAX_CHARS) onChange(next);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className={cn(
            'flex-1 resize-none bg-transparent px-2.5 py-2',
            'text-sm text-text placeholder:text-text-dim',
            'focus:outline-none',
            'disabled:opacity-50',
          )}
        />
        <button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          aria-label="Send message"
          title="Send (Enter)"
          className={cn(
            'mr-1 mb-1 h-7 w-7 shrink-0 rounded-md inline-flex items-center justify-center',
            'transition-colors duration-100',
            'focus:outline-none focus:ring-1 focus:ring-accent/40',
            canSend
              ? 'bg-accent/15 hover:bg-accent/25 text-accent'
              : 'text-text-dim cursor-not-allowed',
          )}
        >
          <SendGlyph />
        </button>
      </div>
      <div className="flex justify-between items-center mt-1 px-1 h-3.5">
        <span className="text-[10px] text-text-dim">
          Enter to send · Shift+Enter for newline
        </span>
        {showCounter && (
          <span
            className={cn(
              'text-[10px] tabular-nums',
              charsLeft < 0 ? 'text-error' : 'text-text-dim',
            )}
          >
            {charsLeft}
          </span>
        )}
      </div>
    </div>
  );
}

function SendGlyph() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M8 13V3M8 3L3.5 7.5M8 3L12.5 7.5" />
    </svg>
  );
}
