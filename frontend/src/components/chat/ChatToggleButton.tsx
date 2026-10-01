import { cn } from '@/lib/utils';

interface ChatToggleButtonProps {
  open: boolean;
  onClick: () => void;
  /** Optional unread-message indicator (count or boolean dot). */
  hasUnread?: boolean;
}

/**
 * Pill button in the top bar that opens/closes the chat drawer. Visually
 * matches the existing top-bar text style (text-xs, text-text-muted) so it
 * doesn't shout for attention.
 */
export function ChatToggleButton({ open, onClick, hasUnread }: ChatToggleButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={open}
      aria-label={open ? 'Close chat assistant' : 'Open chat assistant'}
      title={open ? 'Close chat (⌘/Ctrl + .)' : 'Open chat (⌘/Ctrl + .)'}
      className={cn(
        'h-7 px-2.5 rounded-md text-xs font-medium',
        'inline-flex items-center gap-1.5',
        'transition-colors duration-100',
        'focus:outline-none focus:ring-1 focus:ring-accent/40',
        open
          ? 'bg-accent/15 text-accent border border-accent/40 hover:bg-accent/25'
          : 'bg-transparent text-text-muted hover:bg-bg-elevated hover:text-text border border-transparent',
      )}
    >
      <ChatGlyph />
      <span>Chat</span>
      {hasUnread && (
        <span
          aria-hidden
          className="ml-0.5 h-1.5 w-1.5 rounded-full bg-accent"
        />
      )}
    </button>
  );
}

function ChatGlyph() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M2.5 4.5C2.5 3.4 3.4 2.5 4.5 2.5H11.5C12.6 2.5 13.5 3.4 13.5 4.5V9.5C13.5 10.6 12.6 11.5 11.5 11.5H6L3.5 13.5V11.5H4.5C3.4 11.5 2.5 10.6 2.5 9.5V4.5Z" />
    </svg>
  );
}
