// Shared player deep-link / return-navigation contract. Used by PlayerLink.tsx
// and PlayerDashboard.tsx. Mirrors app/player_nav.py's contract byte-for-byte
// (query param names, sessionStorage key format) — the two are separate
// implementations (Python-templated pages vs this React app) sharing one
// wire contract, since no router/store spans both runtimes. See
// PLAYER_LINK_NAV_LOG.md Decision Points A/E for why.
//
// Deep-link URL shape:  /viz/player?player=<id>&origin_view=<url>&origin_label=<label>[&origin_state=<key>]
//   - origin_view:  full return path + query string of the source screen
//   - origin_label: short button-text label, e.g. "Audit"
//   - origin_state: OPTIONAL sessionStorage key already holding a JSON
//     snapshot of state that isn't captured in origin_view's query string
//     (e.g. a client-only sort column or filter toggle). The key is a fixed,
//     well-known name per source screen (not a per-click token) — the source
//     screen keeps that key's value fresh on every state change, so it's
//     always current by the time any link on the page is clicked/opened in
//     a new tab, regardless of click type.
//
// Return-navigation restore handshake:
//   - PlayerDashboard's return button writes { targetPath, state } to
//     sessionStorage under PLAYER_NAV_RESTORE_KEY, then does a full
//     `window.location.href = origin.view` navigation.
//   - The origin screen's own on-load script checks that key; if
//     targetPath matches its own pathname, it applies `state` via its own
//     existing filter/sort functions and clears the key.

export const PLAYER_NAV_RESTORE_KEY = 'pn_restore';

export interface NavOrigin {
  /** Full path + query string to return to, e.g. "/projections/?pos=WR&team=KC". */
  view: string;
  /** Short label for the return button text, e.g. "Audit", "Projections". */
  label: string;
  /** Opaque snapshot of state not already encoded in `view` (filters/sort
   *  held in page-local JS). Absent when the origin screen is fully
   *  URL-driven (e.g. Ownership). */
  state?: unknown;
}

/** Deterministic sessionStorage key for an origin's state snapshot, derived
 *  from its path so every PlayerLink on the same page converges on the same
 *  key without needing it threaded through as a separate prop. */
export function originStateKey(origin: NavOrigin): string {
  return `pn:${origin.view.split('?')[0]}`;
}

/** Builds the Player Dashboard deep-link href for a given player + origin.
 *  Includes `origin_state` automatically when `origin.state` is present —
 *  the caller (PlayerLink) is responsible for keeping that sessionStorage
 *  key's value fresh as the origin's own state changes. */
export function buildPlayerDashboardHref(playerId: string, origin: NavOrigin): string {
  const u = new URLSearchParams({
    player: playerId,
    origin_view: origin.view,
    origin_label: origin.label,
  });
  if (origin.state !== undefined) u.set('origin_state', originStateKey(origin));
  return `/viz/player?${u.toString()}`;
}

/** Reads the current player id + origin descriptor from the dashboard's own
 *  URL on mount. Returns `origin: null` if no origin params are present
 *  (direct open, refresh with lost query, or an existing entry point that
 *  never set them) — callers must fully support that case. */
export function readPlayerNavFromLocation(): { playerId: string | null; origin: NavOrigin | null } {
  const params = new URLSearchParams(window.location.search);
  const playerId = params.get('player');
  const view = params.get('origin_view');
  const label = params.get('origin_label');
  if (!view || !label) return { playerId, origin: null };

  let state: unknown = undefined;
  const stateKey = params.get('origin_state');
  if (stateKey) {
    try {
      const raw = sessionStorage.getItem(stateKey);
      if (raw) state = JSON.parse(raw);
    } catch {
      // sessionStorage unavailable or corrupt payload — fine, state stays undefined.
    }
  }

  return { playerId, origin: { view, label, state } };
}

/** Return-button action: stash the restore payload (if any) for the origin
 *  screen to pick up on load, then do a real full-page navigation back. */
export function navigateToOrigin(origin: NavOrigin): void {
  if (origin.state !== undefined) {
    try {
      const targetPath = origin.view.split('?')[0];
      sessionStorage.setItem(
        PLAYER_NAV_RESTORE_KEY,
        JSON.stringify({ targetPath, state: origin.state }),
      );
    } catch {
      // sessionStorage unavailable — restore just won't happen, filters/sort
      // are lost but navigation itself still works.
    }
  }
  window.location.href = origin.view;
}
