/**
 * Typed access to the app-wide colour tokens.
 *
 * The palette lives in ONE place: `app/static/theme.css`. `index.html` links
 * it, so Tailwind utilities resolve from it automatically. This module covers
 * the cases Tailwind cannot reach — Plotly configs and SVG values that need a
 * resolved colour string rather than a class.
 *
 * It delegates to `window.TOKENS` (app/static/theme.js) so there is a single
 * implementation of the lookup. If that script is missing it reads the custom
 * property directly, so a change in script order degrades to "still correct"
 * rather than "everything grey".
 *
 * NEVER hard-code a hex here. Add the colour to theme.css instead.
 */

interface TokenBridge {
  get(name: string, fallback?: string): string;
  rgba(nameOrColor: string, alpha: number): string;
  pos(code: string, fallback?: string): string;
}

declare global {
  interface Window { TOKENS?: TokenBridge }
}

const FALLBACK = '#808080';

function readVar(name: string): string {
  if (typeof window === 'undefined') return '';
  try {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(`--${name}`)
      .trim();
  } catch {
    return '';
  }
}

/** Resolved colour for a token, e.g. token('accent') -> "rgb(0, 229, 160)". */
export function token(name: string, fallback: string = FALLBACK): string {
  const bridge = typeof window !== 'undefined' ? window.TOKENS : undefined;
  if (bridge) return bridge.get(name, fallback);
  return readVar(name) || fallback;
}

/** Same colour at an alpha, e.g. tokenRgba('accent', 0.15). */
export function tokenRgba(name: string, alpha: number): string {
  const bridge = typeof window !== 'undefined' ? window.TOKENS : undefined;
  if (bridge) return bridge.rgba(name, alpha);
  const v = readVar(`${name}-rgb`);
  return v ? `rgba(${v.split(/[\s,]+/).join(', ')}, ${alpha})` : token(name);
}

/**
 * Hue for a position code. Unknown positions get the muted text colour, never
 * a guessed hue — an invented colour reads as a real encoding.
 */
export function posColor(code: string): string {
  const bridge = typeof window !== 'undefined' ? window.TOKENS : undefined;
  if (bridge) return bridge.pos(code);
  const map: Record<string, string> = {
    QB: 'qb', RB: 'rb', WR: 'wr', TE: 'te',
    DL: 'dl', DE: 'dl', DT: 'dt',
    LB: 'lb',
    DB: 'db', CB: 'db', S: 's', SAF: 's',
  };
  const key = map[(code || '').toUpperCase()];
  return key ? token(key) : token('tx-mut');
}

/** Number of distinct categorical series hues defined in theme.css. */
export const CAT_COUNT = 6;

/**
 * Colour for the nth chart series (team lines, personnel groupings, role
 * splits). Wraps around. The accent is deliberately not in this set: a
 * series must never look like "this is interactive".
 */
export function catColor(i: number): string {
  return token(`cat-${(((i % CAT_COUNT) + CAT_COUNT) % CAT_COUNT) + 1}`);
}
