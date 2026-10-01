import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from 'react';
import { cn } from '@/lib/utils';

/* ──────────────────────────────────────────────────────────────────────
 * Button
 * ────────────────────────────────────────────────────────────────────── */

export type ButtonVariant = 'default' | 'ghost' | 'outline' | 'accent';
export type ButtonSize = 'sm' | 'md' | 'icon';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const buttonVariants: Record<ButtonVariant, string> = {
  default: 'bg-bg-elevated hover:bg-bg-hover text-text border border-border',
  ghost:   'bg-transparent hover:bg-bg-elevated text-text-muted hover:text-text',
  outline: 'bg-transparent hover:bg-bg-elevated text-text border border-border',
  accent:  'bg-accent/15 hover:bg-accent/25 text-accent border border-accent/40',
};

const buttonSizes: Record<ButtonSize, string> = {
  sm:   'h-7 px-2 text-xs',
  md:   'h-9 px-3 text-sm',
  icon: 'h-7 w-7 p-0 text-sm flex items-center justify-center',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'default', size = 'md', className, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-medium',
        'transition-colors duration-100 disabled:opacity-40 disabled:cursor-not-allowed',
        'focus:outline-none focus:ring-1 focus:ring-accent/40',
        buttonVariants[variant],
        buttonSizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = 'Button';

/* ──────────────────────────────────────────────────────────────────────
 * Chip — toggle-able pill, used for years, positions, teams
 * ────────────────────────────────────────────────────────────────────── */

interface ChipProps {
  selected?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  title?: string;
  children: ReactNode;
  className?: string;
}

export function Chip({ selected, disabled, onClick, title, children, className }: ChipProps) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'inline-flex items-center justify-center rounded-md px-2 py-1',
        'text-xs font-medium transition-colors border',
        'focus:outline-none focus:ring-1 focus:ring-accent/40',
        selected
          ? 'bg-accent/15 border-accent/50 text-accent'
          : 'bg-bg-elevated border-border text-text-muted hover:text-text hover:border-border/80',
        disabled && 'opacity-30 cursor-not-allowed hover:bg-bg-elevated',
        className,
      )}
    >
      {children}
    </button>
  );
}

/* ──────────────────────────────────────────────────────────────────────
 * Toggle — on/off switch
 * ────────────────────────────────────────────────────────────────────── */

interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
  disabled?: boolean;
}

export function Toggle({ checked, onChange, label, disabled }: ToggleProps) {
  return (
    <label className={cn('flex items-center gap-2 cursor-pointer select-none',
                          disabled && 'opacity-40 cursor-not-allowed')}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full',
          'transition-colors focus:outline-none focus:ring-1 focus:ring-accent/40',
          checked ? 'bg-accent/80' : 'bg-bg-hover border border-border',
        )}
      >
        <span
          className={cn(
            'inline-block h-3.5 w-3.5 transform rounded-full bg-text',
            'transition-transform duration-150',
            checked ? 'translate-x-5' : 'translate-x-0.5',
          )}
        />
      </button>
      {label && <span className="text-xs text-text-muted">{label}</span>}
    </label>
  );
}

/* ──────────────────────────────────────────────────────────────────────
 * SegmentedControl — 3-way toggle (granularity)
 * ────────────────────────────────────────────────────────────────────── */

interface SegmentedItem<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}
interface SegmentedProps<T extends string> {
  value: T;
  items: SegmentedItem<T>[];
  onChange: (value: T) => void;
}

export function Segmented<T extends string>({ value, items, onChange }: SegmentedProps<T>) {
  return (
    <div className="inline-flex rounded-md bg-bg-elevated border border-border p-0.5">
      {items.map(item => (
        <button
          key={item.value}
          type="button"
          disabled={item.disabled}
          title={item.title}
          onClick={() => !item.disabled && onChange(item.value)}
          className={cn(
            'px-2.5 py-1 text-xs font-medium rounded-[5px] transition-colors',
            'focus:outline-none',
            item.value === value
              ? 'bg-accent/20 text-accent'
              : 'text-text-muted hover:text-text',
            item.disabled && 'opacity-30 cursor-not-allowed hover:text-text-muted',
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────
 * Slider — single-value range input
 * ────────────────────────────────────────────────────────────────────── */

interface SliderProps {
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

export function Slider({ min, max, step = 1, value, onChange, disabled }: SliderProps) {
  const pct = max === min ? 0 : ((value - min) / (max - min)) * 100;
  return (
    <div className="relative w-full">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={e => onChange(Number(e.target.value))}
        className={cn(
          'w-full h-1.5 bg-bg-elevated rounded-full appearance-none cursor-pointer',
          '[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4',
          '[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full',
          '[&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:cursor-grab',
          '[&::-webkit-slider-thumb]:active:cursor-grabbing',
          '[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4',
          '[&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-accent',
          '[&::-moz-range-thumb]:border-0',
          disabled && 'opacity-40 cursor-not-allowed',
        )}
        style={{
          background:
            // 8-digit hex carries alpha (cc = .8); a var() cannot be
            // concatenated with it, so the alpha goes in the rgb() itself.
            `linear-gradient(to right, rgb(var(--accent-rgb) / .8) 0%, ` +
            `rgb(var(--accent-rgb) / .8) ${pct}%, ` +
            `var(--surf-2) ${pct}%, var(--surf-2) 100%)`,
        }}
      />
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────
 * Input — single-line text
 * ────────────────────────────────────────────────────────────────────── */

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        'h-8 w-full rounded-md bg-bg-elevated border border-border px-2.5',
        'text-sm text-text placeholder:text-text-dim',
        'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/20',
        'transition-colors',
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = 'Input';

/* ──────────────────────────────────────────────────────────────────────
 * Popover — light-weight portal-free dropdown anchored under a trigger
 * ────────────────────────────────────────────────────────────────────── */

interface PopoverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactNode;
  children: ReactNode;
  className?: string;
  align?: 'left' | 'right';
  disabled?: boolean;
}

export function Popover({
  open, onOpenChange, trigger, children, className, align = 'left', disabled,
}: PopoverProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onOpenChange(false);
      }
    };
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };
    document.addEventListener('mousedown', handler);
    document.addEventListener('keydown', escHandler);
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('keydown', escHandler);
    };
  }, [open, onOpenChange]);

  return (
    <div className="relative" ref={ref}>
      <div onClick={() => !disabled && onOpenChange(!open)}>{trigger}</div>
      {open && !disabled && (
        <div
          className={cn(
            'absolute z-30 mt-1 min-w-[14rem] rounded-md',
            'bg-bg-card border border-border shadow-xl shadow-black/50',
            'overflow-hidden',
            align === 'right' ? 'right-0' : 'left-0',
            className,
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────
 * Section header — label above each control group
 * ────────────────────────────────────────────────────────────────────── */

interface FieldProps {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}

export function Field({ label, hint, children, className }: FieldProps) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-baseline justify-between">
        <label className="text-[10px] uppercase tracking-wider font-semibold text-text-dim">
          {label}
        </label>
        {hint && <span className="text-[10px] text-text-dim">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────
 * Helper — controlled search input that focuses on open
 * ────────────────────────────────────────────────────────────────────── */

interface SearchInputProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

export function SearchInput({ value, onChange, placeholder, autoFocus }: SearchInputProps) {
  const ref = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (autoFocus && ref.current) ref.current.focus();
  }, [autoFocus]);
  return (
    <div className={cn(
      'flex items-center gap-1.5 px-2 h-8 border-b border-border',
      focused && 'bg-bg-elevated/40',
    )}>
      <SearchIcon />
      <input
        ref={ref}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className="bg-transparent flex-1 text-sm text-text outline-none placeholder:text-text-dim"
      />
    </div>
  );
}

function SearchIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="w-3.5 h-3.5 text-text-dim shrink-0"
    >
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
