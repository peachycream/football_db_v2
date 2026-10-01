import { useState } from 'react';
import { GamedayProvider } from './GamedayProvider';
import { GamedayTicker } from './GamedayTicker';
import { GamedayButton } from './GamedayButton';
import { GamedayDrawer } from './GamedayDrawer';

// Mounted once in the global layout (main.tsx) so the ticker + button +
// drawer appear across every React SPA page (/viz/, /viz/player,
// /viz/offense) sharing one GamedayProvider fetch loop -- never a
// double-fetch just because both the ticker and drawer are on screen.
export function GamedayWidget() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  return (
    <GamedayProvider>
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
    </GamedayProvider>
  );
}
