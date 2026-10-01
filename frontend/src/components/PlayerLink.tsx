import { useEffect } from 'react';
import { cn } from '@/lib/utils';
import {
  buildPlayerDashboardHref,
  originStateKey,
  type NavOrigin,
} from '@/lib/playerNav';

// Per PLAYER_LINK_NAV_LOG.md Decision Point A: none of the 5 named source
// screens (Audit, Ownership, Projections, Off/Def Snaps) are React — they're
// server-rendered Python pages, so this component has no call site among
// them today. Built per the spec anyway for any future screen hosted inside
// this app; the Python screens use the equivalent app/player_nav.py helper,
// sharing the same URL/sessionStorage contract (frontend/src/lib/playerNav.ts).

export interface PlayerLinkProps {
  playerId: string;
  displayName: string;
  origin: NavOrigin;
  className?: string;
}

export default function PlayerLink({ playerId, displayName, origin, className }: PlayerLinkProps) {
  // Keep the origin's state snapshot fresh in sessionStorage as it changes,
  // not written per-click — guarantees it's already current by the time any
  // click variant (left/middle/ctrl) fires, since a real <a href> is used
  // below and middle-click never dispatches a React onClick handler.
  useEffect(() => {
    if (origin.state === undefined) return;
    try {
      sessionStorage.setItem(originStateKey(origin), JSON.stringify(origin.state));
    } catch {
      // sessionStorage unavailable — return-restore just won't happen.
    }
  }, [origin.view, origin.state]);

  return (
    <a
      href={buildPlayerDashboardHref(playerId, origin)}
      className={cn(
        'text-text hover:text-accent transition-colors underline-offset-2 hover:underline',
        className,
      )}
    >
      {displayName}
    </a>
  );
}
