import { lazy, Suspense, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type {
  StatMeta,
  SeasonsResponse,
  QueryResponse,
  QueryConfig,
  SavedViewState,
  SavedViewSummary,
} from '@/types/api';
import { fetchRegistry, fetchSeasons, runQuery } from '@/lib/api';
import { exportDotsAsCSV } from '@/lib/csv';
import { reducer, INITIAL_STATE } from '@/state/queryState';
import { useDebounce } from '@/hooks/useDebounce';
import { Sidebar } from '@/components/Sidebar';
import { ViewsMenu } from '@/components/ViewsMenu';
import { ChatDrawer } from '@/components/chat/ChatDrawer';
import { ChatToggleButton } from '@/components/chat/ChatToggleButton';

// Lazy-loaded: ScatterChart.tsx imports plotly.js-dist-min at module scope
// (Plotly's own React factory instantiates at import time, not render time),
// so splitting it into its own chunk lets the rest of the Scatter Explorer's
// shell (sidebar, header) paint before Plotly's ~4.5MB finishes downloading,
// instead of blocking on it as part of App's own chunk.
const ScatterChart = lazy(() =>
  import('@/components/ScatterChart').then((m) => ({ default: m.ScatterChart })),
);

const CHAT_OPEN_KEY = 'viz.chat.open';

function App() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  const [registry, setRegistry] = useState<StatMeta[]>([]);
  const [seasons, setSeasons] = useState<SeasonsResponse | null>(null);

  const [bootstrapping, setBootstrapping] = useState(true);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const [result, setResult] = useState<QueryResponse | null>(null);
  const [refetching, setRefetching] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);

  // Mobile filter drawer open/closed (chunk 7b) — the w-96 sidebar holds
  // every control needed to use the page at all, so below `lg` it becomes
  // an off-canvas drawer rather than trying to shrink in place. Not
  // persisted (unlike chatOpen) — always starts closed on a fresh mobile
  // load so the chart/results are visible first.
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Chat drawer open/closed — persists across reloads.
  const [chatOpen, setChatOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem(CHAT_OPEN_KEY) === '1';
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(CHAT_OPEN_KEY, chatOpen ? '1' : '0');
    } catch {
      // ignore
    }
    // Recharts caches container width and only re-measures on window resize.
    // Fire one synthetic resize after the drawer's 200ms slide finishes, and
    // a few during the animation so the chart looks smooth rather than
    // popping at the end.
    const tids: number[] = [];
    for (const ms of [50, 120, 220]) {
      tids.push(window.setTimeout(() => {
        window.dispatchEvent(new Event('resize'));
      }, ms));
    }
    return () => tids.forEach(clearTimeout);
  }, [chatOpen]);

  // Cmd/Ctrl+. toggles the chat drawer
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === '.') {
        e.preventDefault();
        setChatOpen((v) => !v);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Debounce the entire query config so rapid edits coalesce into one request
  const debouncedConfig = useDebounce(state.config, 250);

  // -----------------------------------------------------------------------
  // Bootstrap: load registry + seasons once
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [reg, ssn] = await Promise.all([fetchRegistry(), fetchSeasons()]);
        if (cancelled) return;
        setRegistry(reg.stats);
        setSeasons(ssn);
      } catch (e) {
        if (!cancelled) {
          setBootstrapError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setBootstrapping(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // -----------------------------------------------------------------------
  // Refetch on config change (debounced).
  // Skip until X+Y are set; ignore stale responses with a request token.
  // -----------------------------------------------------------------------
  const requestToken = useRef(0);
  useEffect(() => {
    if (bootstrapping || bootstrapError) return;
    const cfg = debouncedConfig;
    if (!cfg.x_stat || !cfg.y_stat) {
      setResult(null);
      return;
    }
    if (cfg.seasons.length === 0) {
      // Backend defaults empty seasons to [2025]; better to show the user
      // an explicit empty state than to silently query the wrong year.
      setResult(null);
      return;
    }
    // Week mode requires a week value. Don't fire the query until the user
    // picks one — the backend would 400 with "week granularity requires a
    // week value", which renders as a transient error in the warnings strip.
    if (cfg.granularity === 'week' && cfg.week == null) {
      setResult(null);
      return;
    }

    const token = ++requestToken.current;
    setRefetching(true);
    setQueryError(null);

    runQuery(cfg)
      .then((res) => {
        if (token !== requestToken.current) return; // stale
        setResult(res);
      })
      .catch((e) => {
        if (token !== requestToken.current) return;
        setQueryError(e instanceof Error ? e.message : String(e));
        // keep previous result visible — don't clear `result`
      })
      .finally(() => {
        if (token === requestToken.current) setRefetching(false);
      });
  }, [debouncedConfig, bootstrapping, bootstrapError]);

  // Saved-view tracking (chunk 5) ─────────────────────────────────────────
  // currentState is the slice that a saved view captures (config + decorations).
  // isDirty compares it to loadedSnapshot via JSON.stringify — cheap because
  // the snapshot only changes on load/save, and the comparison cost is fine
  // for the size of QueryConfig.
  const currentState: SavedViewState = useMemo(() => ({
    config: state.config,
    showQuadrants: state.showQuadrants,
    showLabels: state.showLabels,
    trendline: state.trendline,
  }), [state.config, state.showQuadrants, state.showLabels, state.trendline]);

  const isDirty = useMemo(() => {
    if (!state.loadedSnapshot) return false;
    return JSON.stringify(currentState) !== JSON.stringify(state.loadedSnapshot);
  }, [currentState, state.loadedSnapshot]);

  const handleViewLoad = (loadedState: SavedViewState, summary: SavedViewSummary) => {
    dispatch({
      type: 'load_view',
      value: {
        config: loadedState.config,
        showQuadrants: loadedState.showQuadrants,
        // Views saved before labels existed have no key. The ?? is also what
        // keeps isDirty honest: JSON.stringify drops undefined, so an
        // undefined here would produce a snapshot missing the key while
        // currentState has `showLabels: false` — a permanently dirty view.
        showLabels: loadedState.showLabels ?? false,
        trendline: loadedState.trendline,
        summary,
      },
    });
  };

  const handleViewUnload = () => dispatch({ type: 'unload_view' });

  const handleApplySuggestion = (config: Partial<QueryConfig>) => {
    dispatch({
      type: 'load_view',
      value: {
        config: { ...state.config, ...config },
        showQuadrants: state.showQuadrants,
        showLabels: state.showLabels,
        trendline: state.trendline,
      },
    });
  };

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  if (bootstrapping) {
    return <FullScreenMessage text="Loading registry…" />;
  }
  if (bootstrapError) {
    return (
      <FullScreenMessage
        text={`Failed to load registry: ${bootstrapError}`}
        kind="error"
      />
    );
  }

  const dotCount = result?.dots.length ?? 0;
  const cappedNote = result?.capped ? ' (capped — tighten filters)' : '';
  const tooManyDots = dotCount > 2000;

  return (
    <div className="flex h-full relative lg:static">
      {/* Backdrop — mobile/tablet only, shown while the filter drawer is open */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar: permanent in-flow panel at lg+; off-canvas drawer below lg */}
      <div
        className={
          'fixed inset-y-0 left-0 z-40 transition-transform duration-200 ease-out ' +
          'lg:static lg:z-auto lg:translate-x-0 lg:transition-none ' +
          (sidebarOpen ? 'translate-x-0' : '-translate-x-full')
        }
      >
        <Sidebar
          registry={registry}
          seasons={seasons}
          state={state}
          dispatch={dispatch}
          visibleDots={result?.dots ?? []}
          onRequestClose={() => setSidebarOpen(false)}
        />
      </div>

      <main className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-12 shrink-0 border-b border-border px-4 flex items-center justify-between bg-bg-card">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden h-7 w-7 shrink-0 rounded-md inline-flex items-center justify-center
                         text-text-muted hover:text-text hover:bg-bg-hover transition-colors"
              title="Filters"
              aria-label="Open filters"
            >
              <FilterIcon />
            </button>
            <a
              href="/"
              className="hidden sm:inline text-xs text-text-muted hover:text-text transition-colors"
            >
              ← Home
            </a>
            <h1 className="text-sm font-semibold text-text truncate">Scatter Explorer</h1>
            <span className="hidden md:inline text-[10px] uppercase tracking-wider text-text-dim">
              Football DB
            </span>
            <a
              href="/viz/player"
              className="hidden md:inline text-xs text-text-muted hover:text-text transition-colors"
            >
              Player Dashboard →
            </a>
            <div className="hidden sm:block">
              <ViewsMenu
                currentState={currentState}
                currentViewId={state.loadedView?.view_id ?? null}
                currentViewName={state.loadedView?.name ?? null}
                isDirty={isDirty}
                onLoad={handleViewLoad}
                onUnload={handleViewUnload}
              />
            </div>
          </div>
          <div className="flex items-center gap-3 text-xs">
            {refetching && (
              <span className="text-text-dim flex items-center gap-1.5">
                <Spinner />
                <span className="hidden sm:inline">updating…</span>
              </span>
            )}
            <span className="hidden sm:inline text-text-muted">
              {registry.length} stats · {dotCount} dots
              {cappedNote && (
                <span className="text-warn ml-1">{cappedNote}</span>
              )}
            </span>
            {tooManyDots && !result?.capped && (
              <span
                className="text-warn"
                title="Chart may be slow / cluttered. Try tighter filters."
              >
                ⚠ {dotCount} dots
              </span>
            )}
            <button
              type="button"
              onClick={() => result && exportDotsAsCSV(result, state.config)}
              disabled={!result || result.dots.length === 0}
              className={
                'h-7 px-2.5 rounded-md text-xs flex items-center gap-1.5 ' +
                'bg-bg-elevated hover:bg-bg-hover border border-border ' +
                'text-text-muted hover:text-text transition-colors ' +
                'focus:outline-none focus:ring-1 focus:ring-accent/40 ' +
                'disabled:opacity-40 disabled:cursor-not-allowed ' +
                'disabled:hover:bg-bg-elevated disabled:hover:text-text-muted'
              }
              title={
                !result || result.dots.length === 0
                  ? 'No dots to export'
                  : `Download ${result.dots.length} dots as CSV`
              }
            >
              <DownloadIcon />
              Export CSV
            </button>
            <ChatToggleButton
              open={chatOpen}
              onClick={() => setChatOpen((v) => !v)}
            />
          </div>
        </header>

        {/* Warnings strip */}
        {(queryError || (result?.warnings.length ?? 0) > 0) && (
          <div className="px-4 py-2 border-b border-border bg-bg-card/50 text-xs flex flex-col gap-1">
            {queryError && (
              <div className="text-error">⨯ {queryError}</div>
            )}
            {result?.warnings.map((w, i) => (
              <div key={i} className="text-warn">⚠ {w}</div>
            ))}
          </div>
        )}

        {/* Chart */}
        <div className="flex-1 min-h-0 p-4">
          {result && result.dots.length > 0 ? (
            <Suspense fallback={<ChartLoadingFallback />}>
              <ScatterChart
                data={result}
                showQuadrants={state.showQuadrants}
                showLabels={state.showLabels}
                highlights={state.highlights}
                trendline={state.trendline}
              />
            </Suspense>
          ) : (
            <EmptyState
              hasQuery={!!(state.config.x_stat && state.config.y_stat)}
              noSeasons={state.config.seasons.length === 0}
              refetching={refetching}
            />
          )}
        </div>
      </main>

      <ChatDrawer
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        currentConfig={state.config}
        currentDotCount={dotCount}
        onApplySuggestion={handleApplySuggestion}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tiny presentational helpers
// ---------------------------------------------------------------------------

function FullScreenMessage({
  text, kind = 'info',
}: { text: string; kind?: 'info' | 'error' }) {
  return (
    <div className="h-full w-full flex items-center justify-center">
      <div className={kind === 'error' ? 'text-error' : 'text-text-muted'}>
        {text}
      </div>
    </div>
  );
}

function ChartLoadingFallback() {
  return (
    <div className="h-full w-full flex items-center justify-center border border-dashed border-border rounded-lg">
      <div className="text-text-muted text-sm flex items-center gap-2">
        <Spinner />
        Loading chart…
      </div>
    </div>
  );
}

function EmptyState({
  hasQuery, noSeasons, refetching,
}: { hasQuery: boolean; noSeasons: boolean; refetching: boolean }) {
  let message: string;
  if (!hasQuery) {
    message = 'Pick an X and Y stat to see results.';
  } else if (noSeasons) {
    message = 'Pick at least one season to query.';
  } else if (refetching) {
    message = 'Loading…';
  } else {
    message = 'No dots match these filters. Try widening positions, teams, or years — or lowering the threshold.';
  }
  return (
    <div className="h-full w-full flex items-center justify-center border border-dashed border-border rounded-lg">
      <div className="text-center max-w-sm">
        <p className="text-text-muted text-sm">{message}</p>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <span
      className="inline-block w-2.5 h-2.5 rounded-full border border-text-dim border-t-accent animate-spin"
      style={{ borderTopColor: 'var(--accent)' }}
    />
  );
}

function FilterIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="w-4 h-4 shrink-0"
      aria-hidden="true"
    >
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="w-3.5 h-3.5 shrink-0"
      aria-hidden="true"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

export default App;
