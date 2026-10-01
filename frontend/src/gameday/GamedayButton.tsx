import { useGameday } from './GamedayProvider';
import { flattenMatchups, matchupIsLive } from './helpers';

interface Props {
  onOpen: () => void;
}

export function GamedayButton({ onOpen }: Props) {
  const { data } = useGameday();
  if (data?.paused) return null;
  const liveCount = data ? flattenMatchups(data).filter((f) => matchupIsLive(f.matchup)).length : 0;

  return (
    <button
      type="button"
      onClick={onOpen}
      title="Game-day tracker"
      aria-label="Open game-day tracker"
      className="fixed z-40 bottom-12 right-4 h-11 w-11 rounded-full bg-bg-elevated border border-border
                 shadow-lg flex items-center justify-center hover:bg-bg-hover transition-colors"
    >
      <span className="text-base" aria-hidden="true">🏈</span>
      {liveCount > 0 && (
        <span
          className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-accent
                     text-bg text-[10px] font-semibold flex items-center justify-center"
        >
          {liveCount}
        </span>
      )}
    </button>
  );
}
