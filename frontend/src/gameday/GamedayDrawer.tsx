import { useEffect, useRef, useState } from 'react';
import { useGameday } from './GamedayProvider';
import { flattenMatchups, fmtScore, GAME_STATE_LABEL, isStale } from './helpers';
import type { GamedaySide, GamedayPlayer } from '@/types/gameday';

interface Props {
  open: boolean;
  selectedKey: string | null;
  onClose: () => void;
}

export function GamedayDrawer({ open, selectedKey, onClose }: Props) {
  const { data, loading, error } = useGameday();
  const selectedRef = useRef<HTMLDivElement | null>(null);
  // Off by default -- these are approximate (MFL's own projections for MFL
  // leagues, generic PPR for Sleeper leagues, neither exactly matches these
  // leagues' custom/IDP scoring), so they're opt-in per Phase 3's spec.
  const [showProjected, setShowProjected] = useState(false);

  useEffect(() => {
    if (open && selectedKey && selectedRef.current) {
      selectedRef.current.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }, [open, selectedKey]);

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/50"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <div
        className={
          'fixed top-0 right-0 z-50 h-full w-full sm:w-[420px] bg-bg-card border-l border-border ' +
          'transition-transform duration-200 ease-out flex flex-col ' +
          (open ? 'translate-x-0' : 'translate-x-full')
        }
        aria-hidden={!open}
      >
        <div className="h-12 shrink-0 border-b border-border px-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">Game Day</h2>
          <div className="flex items-center gap-3">
            {data && isStale(data) && (
              <span className="text-[10px] text-warn" title="Backend is having trouble refreshing one or more sources">
                ⚠ reconnecting
              </span>
            )}
            {data && (
              <span className="text-[10px] text-text-dim">
                updated {Math.round(data.cache_age_seconds)}s ago
              </span>
            )}
            <button
              type="button"
              onClick={onClose}
              className="h-7 w-7 rounded-md flex items-center justify-center text-text-muted
                         hover:text-text hover:bg-bg-hover transition-colors"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </div>
        <label className="shrink-0 flex items-center gap-1.5 px-4 py-1.5 border-b border-border/60
                           text-[10px] text-text-dim cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showProjected}
            onChange={(e) => setShowProjected(e.target.checked)}
            className="accent-accent"
          />
          Show projected finish (approximate, off by default)
        </label>

        <div className="flex-1 overflow-y-auto">
          {loading && !data && (
            <div className="p-4 text-xs text-text-muted">Loading…</div>
          )}
          {error && (
            <div className="p-4 text-xs text-error">⨯ {error}</div>
          )}
          {data && data.errors.length > 0 && (
            <div className="px-4 py-2 text-[11px] text-warn border-b border-border/60">
              {data.errors.map((e, i) => (
                <div key={i}>⚠ {e.source}/{e.league_id}: {e.message}</div>
              ))}
            </div>
          )}
          {data && flattenMatchups(data).length === 0 && (
            <div className="p-4 text-xs text-text-muted">No leagues resolved.</div>
          )}
          {data && flattenMatchups(data).map((f) => (
            <div
              key={f.key}
              ref={f.key === selectedKey ? selectedRef : undefined}
              className={
                'border-b border-border/60 p-3 ' +
                (f.key === selectedKey ? 'bg-bg-hover/40' : '')
              }
            >
              <div className="text-[10px] uppercase tracking-wide text-text-dim mb-2">
                {f.league.name}
                {f.matchup.type !== 'h2h' && <span className="ml-1">· {f.matchup.type}</span>}
              </div>
              {f.matchup.opponent ? (
                <div className="grid grid-cols-2 gap-2">
                  <SideCard side={f.matchup.me} showProjected={showProjected} />
                  <SideCard side={f.matchup.opponent} showProjected={showProjected} />
                </div>
              ) : (
                <SideCard side={f.matchup.me} poolRank={f.matchup.pool_rank} showProjected={showProjected} />
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function SideCard({
  side, poolRank, showProjected,
}: { side: GamedaySide; poolRank?: number | null; showProjected: boolean }) {
  const groups: { label: string; players: GamedayPlayer[] }[] = [
    { label: 'In play', players: side.players.filter((p) => p.game_state === 'in') },
    { label: 'Yet to play', players: side.players.filter((p) => p.game_state === 'pre') },
    { label: 'Done', players: side.players.filter((p) => p.game_state === 'post' || p.game_state === 'bye') },
  ];
  const remaining = side.players
    .filter((p) => p.game_state !== 'post' && p.game_state !== 'bye' && p.projected_points != null)
    .reduce((sum, p) => sum + (p.projected_points as number), 0);
  const projectedFinish = side.score + remaining;

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-xs font-medium text-text truncate">{side.name}</span>
        <span className="text-sm font-semibold text-text tabular-nums">{fmtScore(side.score)}</span>
      </div>
      {showProjected && (
        <div
          className="text-[10px] text-text-dim mb-1"
          title="Actual points so far + each not-done starter's full-game projection -- approximate, not a live-adjusted remaining total"
        >
          proj finish: <span className="text-text">{fmtScore(projectedFinish)}</span>
        </div>
      )}
      {poolRank != null && (
        <div className="text-[10px] text-text-dim mb-1">Pool rank #{poolRank}</div>
      )}
      <div className="text-[10px] text-text-dim mb-2">
        {side.starters_in_play} in play · {side.starters_yet_to_play} yet · {side.starters_done} done
      </div>
      {groups.map((g) => g.players.length > 0 && (
        <div key={g.label} className="mb-2">
          <div className="text-[9px] uppercase tracking-wide text-text-dim mb-0.5">{g.label}</div>
          {g.players.map((p, i) => (
            <div key={i} className="flex items-center justify-between text-[11px] py-0.5">
              <span className="text-text-muted truncate flex-1">
                {p.name} <span className="text-text-dim">{p.nfl_team ?? ''}</span>
              </span>
              <span className="text-text-dim ml-2 shrink-0">
                {p.game_state === 'in' && p.period != null
                  ? `Q${p.period} ${p.clock ?? ''}`
                  : GAME_STATE_LABEL[p.game_state]}
              </span>
              <span className="text-text tabular-nums ml-2 w-10 text-right shrink-0">
                {fmtScore(p.points)}
              </span>
              {showProjected && p.game_state !== 'post' && p.game_state !== 'bye' && p.projected_points != null && (
                <span
                  className="text-text-dim tabular-nums ml-1 w-14 text-right shrink-0"
                  title="Full-game projection, not a live-adjusted remaining total -- these upstream APIs don't expose that distinction"
                >
                  (proj {fmtScore(p.projected_points)})
                </span>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
