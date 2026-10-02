import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { GamedayResponse } from '@/types/gameday';

// Single shared fetch loop for the whole page -- GamedayTicker and
// GamedayButton/Drawer both read from this context so opening the drawer
// never triggers a second fetch on top of the ticker's.
//
// Polling: one fetch on mount, then the response's own `any_live` decides
// the next delay -- 30s while any game is live (matches the backend's live
// TTL), 300s while idle (matches the backend's idle TTL) rather than
// stopping outright, so a tab left open through the offseason still
// notices Week 1 starting without a manual reload. Paused while the tab
// is hidden (Page Visibility API), with an immediate refetch on return.
const POLL_LIVE_MS = 30_000;
const POLL_IDLE_MS = 300_000;

interface GamedayContextValue {
  data: GamedayResponse | null;
  loading: boolean;
  error: string | null;
  /** false once the server answers 404: v2 has no /gameday/live route yet (the v1 tracker is not ported),
   *  so the widget renders nothing and stops polling instead of showing a 404 in the drawer. */
  available: boolean;
}

const GamedayContext = createContext<GamedayContextValue>({ data: null, loading: true, error: null, available: true });

export function useGameday() {
  return useContext(GamedayContext);
}

// Dev/offseason testing hook: ?gameday_replay=SEASON:WEEK on the current
// page's URL is forwarded to the backend's own ?replay= param. Inert
// unless explicitly present -- see GAMEDAY_TRACKER_BUILD.md #8.
function replayParam(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('gameday_replay');
  } catch {
    return null;
  }
}

export function GamedayProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<GamedayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(true);

  const fetchOnce = useCallback(async (): Promise<GamedayResponse | null | 'unavailable'> => {
    try {
      const replay = replayParam();
      const url = replay ? `/gameday/live?replay=${encodeURIComponent(replay)}` : '/gameday/live';
      const res = await fetch(url);
      if (res.status === 404) {   // no such route: not an outage, nothing to poll for
        setAvailable(false);
        setData(null);
        setError(null);
        return 'unavailable';
      }
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: GamedayResponse = await res.json();
      setData(json);
      setError(null);
      return json;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    let unavailable = false;

    async function tick() {
      const json = await fetchOnce();
      if (json === 'unavailable') unavailable = true;
      if (cancelled || unavailable || document.visibilityState === 'hidden') return;
      const delay = json && json !== 'unavailable' && json.any_live ? POLL_LIVE_MS : POLL_IDLE_MS;
      timer = window.setTimeout(tick, delay);
    }

    function onVisibility() {
      if (unavailable) return;
      if (document.visibilityState === 'visible') {
        if (timer != null) window.clearTimeout(timer);
        tick();
      } else if (timer != null) {
        window.clearTimeout(timer);
        timer = null;
      }
    }

    tick();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      cancelled = true;
      if (timer != null) window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [fetchOnce]);

  return (
    <GamedayContext.Provider value={{ data, loading, error, available }}>
      {children}
    </GamedayContext.Provider>
  );
}
