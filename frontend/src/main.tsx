import React, { Suspense, lazy } from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';

// Lazy-loaded per page (chunk 7b: Plotly code-splitting) -- App.tsx is the
// only page that imports Plotly (plotly.js-dist-min, ~1MB+ minified), which
// used to ship to EVERY page load (PlayerDashboard/TeamOffenseDashboard
// included) because main.tsx statically imported all three. Since only one
// page ever renders (decided synchronously from the URL, below), Rollup
// gives each React.lazy() import its own chunk -- Plotly now only downloads
// for visitors actually on the Scatter Explorer.
const App = lazy(() => import('./App'));
const PlayerDashboard = lazy(() => import('./pages/PlayerDashboard'));
const TeamOffenseDashboard = lazy(() => import('./pages/TeamOffenseDashboard'));
const TeamDefenseDashboard = lazy(() => import('./pages/TeamDefenseDashboard'));
const DraftBoard = lazy(() => import('./pages/DraftBoard'));
const DraftGrades = lazy(() => import('./pages/DraftGrades'));
const MatchupTool = lazy(() => import('./pages/MatchupTool'));

// Flask serves index.html for any /viz/* path, so we pick the page from the
// URL here. No router dependency; switching pages is a normal full navigation
// via plain anchors (see the cross-links in App.tsx and PlayerDashboard.tsx).
const isDashboard = /\/viz\/player\/?$/.test(window.location.pathname);
const isOffense = /\/viz\/offense\/?$/.test(window.location.pathname);
const isDefense = /\/viz\/defense\/?$/.test(window.location.pathname);
// Draft grades: /viz/draft-grades. Checked BEFORE isDraft so the /viz/draft
// prefix can't swallow it (its regex is anchored, but order is defensive).
const isDraftGrades = /\/viz\/draft-grades\/?$/.test(window.location.pathname);
// Draft board: /viz/draft is the canonical client-side route; /draft/ is a
// Flask alias serving the same index.html (the runbook names that path).
const isDraft = /(\/viz\/draft|\/draft)\/?$/.test(window.location.pathname);
// Matchup tool: /viz/matchups is canonical; /matchups/ is a Flask alias
// serving the same index.html (MATCHUP_TOOL_BUILD.md names that path).
const isMatchups = /(\/viz\/matchups|\/matchups)\/?$/.test(window.location.pathname);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Suspense fallback={<PageLoadingFallback />}>
      {isDraftGrades ? <DraftGrades /> : isMatchups ? <MatchupTool /> : isDraft ? <DraftBoard /> : isOffense ? <TeamOffenseDashboard /> : isDefense ? <TeamDefenseDashboard /> : isDashboard ? <PlayerDashboard /> : <App />}
    </Suspense>
  </React.StrictMode>,
);

function PageLoadingFallback() {
  return (
    <div className="h-screen w-screen flex items-center justify-center bg-bg text-text-muted text-sm">
      Loading…
    </div>
  );
}
