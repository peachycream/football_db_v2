import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a value according to a format_str from the stat registry.
 * Supports: '0', '0.0', '0.00', '0.0%', etc.
 */
export function formatStat(val: number | string | null, fmt: string | null): string {
  if (val === null || val === undefined || val === '') return '—';
  if (typeof val === 'string') return val;
  if (!fmt) return String(val);

  const isPct = fmt.endsWith('%');
  const decimalMatch = fmt.match(/0\.(0+)/);
  const decimals = decimalMatch ? decimalMatch[1].length : 0;

  // Heuristic: if format is '%' and value is between 0 and 1, multiply by 100
  const num = isPct && Math.abs(val) <= 1 ? val * 100 : val;
  return num.toFixed(decimals) + (isPct ? '%' : '');
}

/**
 * Toggle membership in a string array. Returns a new array.
 */
export function toggleMember<T>(arr: T[], item: T): T[] {
  return arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item];
}

/**
 * Substring-match a multi-team season string against a set of selected teams.
 * Example: row team "LV, NYJ" matches if either "LV" or "NYJ" is selected.
 */
export function matchesTeamFilter(rowTeam: string | null, selected: string[]): boolean {
  if (!selected.length) return true;
  if (!rowTeam) return false;
  const parts = rowTeam.split(',').map(p => p.trim());
  return parts.some(p => selected.includes(p));
}
