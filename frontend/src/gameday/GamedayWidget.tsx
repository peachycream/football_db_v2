import { useState } from 'react';
import { GamedayProvider, useGameday } from './GamedayProvider';
import { GamedayTicker } from './GamedayTicker';
import { GamedayButton } from './GamedayButton';
import { GamedayDrawer } from './GamedayDrawer';

// Mounted once in the global layout (main.tsx) so the ticker + button +
// drawer appear across every React SPA page (/viz/, /viz/player,
// /viz/offense) sharing one GamedayProvider fetch loop -- never a
// double-fetch just because both the ticker and drawer are on screen.
export function GamedayWidget() {
  return (
    <GamedayProvider>
      <GamedayUi />
    </GamedayProvider>
  );
}

function GamedayUi() {
  const { available } = useGameday();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  // v2 has no /gameday/live route yet (REBUILD_LOG: Game Day not ported): show nothing rather than a 404.
  if (!available) return null;
  return (
    <>
      <GamedayTicker
        onSelect={(key) => {
          setSelectedKey(key);
          setDrawerOpen(true);
        }}
      />
      <GamedayButton onOpen={() => setDrawerOpen(true)} />
      <GamedayDrawer
        open={drawerOpen}
        selectedKey={selectedKey}
        onClose={() => setDrawerOpen(false)}
      />
    </>
  );
}
