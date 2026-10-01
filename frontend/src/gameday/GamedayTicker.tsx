import { useGameday } from './GamedayProvider';
import {
  chipLabel, closestLiveMatchupKey, flattenMatchups, isStale,
  matchupIsLive, matchupStateLabel, sortForTicker, yetToPlayLabel,
} from './helpers';
import type { FlatMatchup } from './helpers';

interface Props {
  onSelect: (key: string) => void;
}

export function GamedayTicker({ onSelect }: Props) {
  const { data, error } = useGameday();
  if (error || !data || data.leagues.length === 0) return null;

  const flats = sortForTicker(flattenMatchups(data));
  if (flats.length === 0) return null;

  const stale = isStale(data);

  if (!data.any_live) {
    return (
      <div className="fixed bottom-0 left-0 right-0 z-40 h-7 bg-bg-card border-t border-border
                       flex items-center justify-between px-3 text-[11px] text-text-dim">
        <span>
          No live games
          {data.replay && <span className="ml-2 text-text-dim/60">(replay {data.season}:{data.week})</span>}
        </span>
        {stale && <StaleBadge />}
      </div>
    );
  }

  const closestKey = closestLiveMatchupKey(flats);

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 h-9 bg-bg-card border-t border-border
                     flex items-center overflow-x-auto">
      <div className="flex items-stretch flex-1 min-w-0">
        {flats.map((f) => (
          <TickerChip key={f.key} flat={f} isClosest={f.key === closestKey} onSelect={onSelect} />
        ))}
      </div>
      {stale && (
        <div className="shrink-0 px-2 border-l border-border/60">
          <StaleBadge />
        </div>
      )}
    </div>
  );
}

function StaleBadge() {
  return (
    <span className="text-[10px] text-warn flex items-center gap-1" title="Backend is having trouble refreshing one or more sources">
      ⚠ reconnecting
    </span>
  );
}

function TickerChip({
  flat, isClosest, onSelect,
}: { flat: FlatMatchup; isClosest: boolean; onSelect: (key: string) => void }) {
  const live = matchupIsLive(flat.matchup);
  const yet = yetToPlayLabel(flat.matchup);
  const stateLabel = matchupStateLabel(flat.matchup);
  return (
    <button
      type="button"
      onClick={() => onSelect(flat.key)}
      className={
        'shrink-0 h-9 px-3 flex items-center gap-2 border-r border-border/60 ' +
        'hover:bg-bg-hover transition-colors text-xs whitespace-nowrap ' +
        (isClosest ? 'bg-accent/10' : '')
      }
      title={flat.league.name}
    >
      {isClosest && <span title="Closest live matchup">🔥</span>}
      {live && (
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" aria-hidden="true" />
      )}
      <span className="text-text-dim uppercase tracking-wide text-[9px]">{flat.league.name}</span>
      {stateLabel && (
        <span
          className={
            'text-[9px] font-semibold px-1 rounded ' +
            (stateLabel === 'LIVE' ? 'text-accent' : 'text-text-dim')
          }
        >
          {stateLabel}
        </span>
      )}
      <span className="text-text">{chipLabel(flat.matchup)}</span>
      {yet && <span className="text-text-dim text-[10px]">{yet}</span>}
    </button>
  );
}
