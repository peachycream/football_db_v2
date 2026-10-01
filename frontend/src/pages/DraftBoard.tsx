import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import { Button, Chip, SearchInput, Segmented } from '@/components/ui/primitives';
import {
  DRAFT_LEAGUES, fetchBoard, fetchDraftState, fetchPredict, fetchRoster,
  fetchScarcity, fetchSurvival, saveTier, isMock,
  type BoardPlayer, type BoardResponse, type DraftState, type PredictResponse,
  type RosterResponse, type ScarcityResponse, type SurvivalResponse,
} from '@/lib/draftApi';

// Auto-refresh is ADAPTIVE and off by default. Drafts start 2026-08-01 07:00 ET;
// until then every league's picks table is a pre-filled skeleton with zero picks
// made, so a fixed 60s timer just re-fetched identical data ~1,440x/day per open
// tab (it ran for days in mid-July before this was fixed). Even during the live
// draft the pick timers are EIGHT HOURS, so a 2-minute cadence is far more
// responsive than the draft can possibly move.
const DRAFT_START_MS = Date.parse('2026-08-01T07:00:00-04:00');
const PRE_DRAFT_LEAD_MS = 60 * 60 * 1000;   // arm the timer 1h before the first pick
const REFRESH_LIVE_MS = 600_000;            // live draft, 8-hour pick timers (10 min; server _poll_ttl 90s stays below it)
const SURVIVAL_WHEN_QUEUE_LTE = 10; // runbook Phase 4: hide unless pick is close
const SURVIVAL_TOP_N = 10;

/** null = no auto-refresh (manual button only). */
function refreshIntervalMs(state: DraftState | null, mock: boolean): number | null {
  if (mock) return null;                       // fixtures never change on their own
  if (state?.draft_complete) return null;      // nothing left to poll for
  if (Date.now() < DRAFT_START_MS - PRE_DRAFT_LEAD_MS) return null;
  return REFRESH_LIVE_MS;
}

type SortKey = 'composite' | 'adp' | 'tier';

const BAND_LABEL: Record<string, string> = { rookie: 'ROOKIE', fa: 'FA', devy: 'DEVY' };
const BAND_CLASS: Record<string, string> = {
  rookie: 'bg-accent/15 text-accent border-accent/30',
  fa: 'bg-warn/15 text-warn border-warn/30',
  devy: 'bg-info/15 text-info border-info/30',
};

function num(v: number | null | undefined, d = 1): string {
  return v == null ? '—' : v.toFixed(d);
}

function useLeagueFromUrl(): [string, (v: string) => void] {
  const [league, setLeague] = useState<string>(() => {
    const u = new URLSearchParams(window.location.search).get('league');
    return DRAFT_LEAGUES.some((l) => l.id === u) ? (u as string) : DRAFT_LEAGUES[0].id;
  });
  const set = useCallback((v: string) => {
    setLeague(v);
    const url = new URL(window.location.href);
    url.searchParams.set('league', v);
    window.history.replaceState({}, '', url);   // persists selection in the URL
  }, []);
  return [league, set];
}

export default function DraftBoard() {
  const [league, setLeague] = useLeagueFromUrl();
  const [band, setBand] = useState<string>('');
  const [pos, setPos] = useState<string>('');
  const [classYear, setClassYear] = useState<string>('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('composite');

  const [state, setState] = useState<DraftState | null>(null);
  const [allStates, setAllStates] = useState<Record<string, DraftState>>({});
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [roster, setRoster] = useState<RosterResponse | null>(null);
  const [scarcity, setScarcity] = useState<ScarcityResponse | null>(null);
  const [predict, setPredict] = useState<PredictResponse | null>(null);
  const [survival, setSurvival] = useState<Record<string, SurvivalResponse>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const reqToken = useRef(0);

  // allSettled, NOT all: on draft day a single slow/failed endpoint must never
  // blank the board. Each panel degrades independently; failures surface as a
  // non-blocking banner while everything that did load still renders.
  const load = useCallback(async () => {
    const token = ++reqToken.current;
    const [s, b, r, sc, p] = await Promise.allSettled([
      fetchDraftState(league),
      fetchBoard(league, band || undefined, pos || undefined),
      fetchRoster(league),
      fetchScarcity(league),
      fetchPredict(league, 3),
    ]);
    if (token !== reqToken.current) return;

    if (s.status === 'fulfilled') {
      setState(s.value);
      setAllStates((prev) => ({ ...prev, [league]: s.value }));
    }
    if (b.status === 'fulfilled') setBoard(b.value);
    if (r.status === 'fulfilled') setRoster(r.value);
    if (sc.status === 'fulfilled') setScarcity(sc.value);
    if (p.status === 'fulfilled') setPredict(p.value);
    else setPredict(null);

    const failed = [
      s.status === 'rejected' && 'state',
      b.status === 'rejected' && 'board',
      r.status === 'rejected' && 'roster',
      sc.status === 'rejected' && 'scarcity',
      p.status === 'rejected' && 'predict',
    ].filter(Boolean) as string[];
    setErr(failed.length ? `Unavailable: ${failed.join(', ')} (other panels still live)` : null);
    setLastRefresh(new Date());
    setLoading(false);
  }, [league, band, pos]);

  useEffect(() => { setLoading(true); load(); }, [load]);

  // on-clock badges need every league's state, not just the active one
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const entries = await Promise.all(
        DRAFT_LEAGUES.map(async (l) => {
          try { return [l.id, await fetchDraftState(l.id)] as const; }
          catch { return null; }
        }),
      );
      if (cancelled) return;
      const next: Record<string, DraftState> = {};
      entries.forEach((e) => { if (e) next[e[0]] = e[1]; });
      setAllStates((prev) => ({ ...prev, ...next }));
    })();
    return () => { cancelled = true; };
  }, []);

  const autoMs = refreshIntervalMs(state, isMock());
  useEffect(() => {
    if (autoMs == null) return;               // pre-draft / mock / complete -> manual only
    const t = setInterval(load, autoMs);
    return () => clearInterval(t);
  }, [load, autoMs]);

  const queue = state?.turon_queue_position ?? null;
  const showSurvival = queue != null && queue <= SURVIVAL_WHEN_QUEUE_LTE;

  const rows = useMemo(() => {
    let r = board?.players ?? [];
    if (classYear) r = r.filter((p) => String(p.draft_class ?? '') === classYear);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      r = r.filter((p) => (p.full_name ?? p.player_id).toLowerCase().includes(q));
    }
    const sorted = [...r];
    if (sort === 'composite') {
      sorted.sort((a, b) => (a.composite_rank ?? 1e9) - (b.composite_rank ?? 1e9));
    } else if (sort === 'adp') {
      sorted.sort((a, b) => (a.adp ?? 1e9) - (b.adp ?? 1e9));
    } else {
      sorted.sort((a, b) => (a.tier ?? 1e9) - (b.tier ?? 1e9)
        || (a.composite_rank ?? 1e9) - (b.composite_rank ?? 1e9));
    }
    return sorted;
  }, [board, search, sort, classYear]);

  // survival only when the pick is close, only for the visible top N
  useEffect(() => {
    if (!showSurvival) { setSurvival({}); return; }
    let cancelled = false;
    const targets = rows.slice(0, SURVIVAL_TOP_N).map((p) => p.player_id);
    (async () => {
      const out: Record<string, SurvivalResponse> = {};
      await Promise.all(targets.map(async (pid) => {
        try { out[pid] = await fetchSurvival(league, pid); } catch { /* ignore */ }
      }));
      if (!cancelled) setSurvival(out);
    })();
    return () => { cancelled = true; };
  }, [showSurvival, league, rows.map((p) => p.player_id).slice(0, SURVIVAL_TOP_N).join(',')]);

  const positions = useMemo(() => {
    const s = new Set<string>();
    (board?.players ?? []).forEach((p) => { if (p.position) s.add(p.position); });
    return Array.from(s).sort();
  }, [board]);

  const hasDevy = (scarcity?.scarcity?.devy ?? null) != null;

  return (
    <div className="min-h-screen bg-bg text-text">
      {/* ── header + league switcher ─────────────────────────────────────── */}
      <div className="border-b border-border bg-bg-card/60 sticky top-0 z-20 backdrop-blur">
        <div className="px-4 py-3 flex items-center gap-3 flex-wrap">
          <a href="/" className="text-xs text-text-dim hover:text-accent mr-2">← Hub</a>
          <h1 className="text-base font-semibold tracking-tight">Draft Board</h1>
          {isMock() && (
            <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border border-warn/40 bg-warn/10 text-warn">
              mock
            </span>
          )}
          <div className="flex-1" />
          <span className="text-xs text-text-dim">
            {lastRefresh ? `updated ${lastRefresh.toLocaleTimeString()}` : '—'}
          </span>
          <span
            className="text-[10px] text-text-dim"
            title={autoMs == null
              ? 'Auto-refresh arms 1 hour before the first pick (2026-08-01 07:00 ET). Use Refresh until then.'
              : `Auto-refreshing every ${Math.round(autoMs / 1000)}s`}
          >
            {autoMs == null ? 'auto: off' : `auto: ${Math.round(autoMs / 1000)}s`}
          </span>
          <Button variant="outline" size="sm" onClick={() => load()}>Refresh</Button>
        </div>

        <div className="px-4 pb-2 flex gap-2 overflow-x-auto">
          {DRAFT_LEAGUES.map((l) => {
            const st = allStates[l.id];
            const onClock = st && !st.draft_complete && st.on_clock === st.turon_franchise;
            const q = st?.turon_queue_position ?? null;
            const active = l.id === league;
            return (
              <button
                key={l.id}
                onClick={() => setLeague(l.id)}
                className={cn(
                  'shrink-0 px-3 py-1.5 rounded-md border text-xs transition-colors',
                  active
                    ? 'border-accent/50 bg-accent/10 text-accent'
                    : 'border-border bg-bg-elevated text-text-muted hover:bg-bg-hover',
                )}
              >
                <span className="font-medium">{l.short}</span>
                {/* on-clock badge: the most important element on the page */}
                {onClock ? (
                  <span className="ml-2 px-1.5 py-0.5 rounded bg-accent text-bg font-semibold animate-pulse">
                    ON CLOCK
                  </span>
                ) : q != null ? (
                  <span className={cn('ml-2 px-1.5 py-0.5 rounded',
                    q <= 3 ? 'bg-warn/20 text-warn' : 'bg-bg-hover text-text-dim')}>
                    in {q}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      {err && <div className="mx-4 mt-3 px-3 py-2 rounded border border-error/40 bg-error/10 text-error text-xs">{err}</div>}

      <div className="flex gap-4 p-4 items-start">
        {/* ── main column ────────────────────────────────────────────────── */}
        <div className="flex-1 min-w-0">
          {/* filters */}
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <Segmented
              value={band as any}
              items={[
                { value: '', label: 'All' },
                { value: 'rookie', label: 'Rookie' },
                { value: 'fa', label: 'FA' },
                ...(hasDevy ? [{ value: 'devy', label: 'Devy' }] : []),
              ] as any}
              onChange={(v: any) => { setBand(v); setClassYear(''); }}
            />
            <div className="w-52"><SearchInput value={search} onChange={setSearch} placeholder="Search player…" /></div>
            <Segmented
              value={sort}
              items={[
                { value: 'composite', label: 'Composite' },
                { value: 'adp', label: 'ADP' },
                { value: 'tier', label: 'Tier' },
              ]}
              onChange={(v) => setSort(v as SortKey)}
            />
            <div className="flex gap-1 flex-wrap">
              <Chip selected={pos === ''} onClick={() => setPos('')}>All pos</Chip>
              {positions.map((p) => (
                <Chip key={p} selected={pos === p} onClick={() => setPos(pos === p ? '' : p)}>{p}</Chip>
              ))}
            </div>
            {band === 'devy' && (
              <div className="flex gap-1">
                {['2027', '2028', '2029'].map((c) => (
                  <Chip key={c} selected={classYear === c} onClick={() => setClassYear(classYear === c ? '' : c)}>
                    {c}
                  </Chip>
                ))}
              </div>
            )}
          </div>

          <div className="text-xs text-text-dim mb-2">
            {loading ? 'Loading…' : `${rows.length} available`}
            {board ? ` · ${board.unavailable_count} unavailable` : ''}
            {showSurvival && <span className="ml-2 text-warn">· survival shown (pick in {queue})</span>}
          </div>

          <BoardTable
            rows={rows}
            league={league}
            showSurvival={showSurvival}
            survival={survival}
            onSaved={load}
          />
        </div>

        {/* ── right rail ─────────────────────────────────────────────────── */}
        <aside className="w-[320px] shrink-0 space-y-3">
          <Panel title="My Roster & Holes">
            {roster ? (
              <>
                <div className="text-xs text-text-dim mb-2">
                  franchise {roster.franchise} · {roster.rostered_count} rostered
                </div>
                <div className="space-y-1">
                  {roster.hole_map.map((h) => (
                    <div key={h.position} className="flex items-center gap-2 text-xs">
                      <span className="w-8 font-mono text-text-muted">{h.position}</span>
                      <div className="flex-1 h-1.5 rounded bg-bg-hover overflow-hidden">
                        <div
                          className={cn('h-full', h.hole > 0 ? 'bg-error' : 'bg-accent')}
                          style={{ width: `${Math.min(100, (h.rostered / Math.max(1, h.required_min)) * 100)}%` }}
                        />
                      </div>
                      <span className="w-14 text-right text-text-dim">
                        {h.rostered}/{h.required_min}
                      </span>
                      {h.hole > 0 && <span className="text-error font-semibold">-{h.hole}</span>}
                    </div>
                  ))}
                </div>
              </>
            ) : <Empty />}
          </Panel>

          <Panel title="Next 3 Picks — position odds" hint="estimate">
            {predict?.next_picks?.length ? (
              <div className="space-y-2">
                {predict.next_picks.map((p) => (
                  <div key={p.overall_pick} className="text-xs">
                    <div className="flex justify-between text-text-dim mb-0.5">
                      <span>#{p.overall_pick} · R{p.round} · fr {p.franchise}</span>
                      {p.tendency_flat && <span title="manager has <2 matched drafts">flat prior</span>}
                    </div>
                    <div className="flex gap-1">
                      {p.top_positions.map((pos2) => (
                        <span key={pos2} className="px-1.5 py-0.5 rounded bg-bg-hover text-text-muted">
                          {pos2} {Math.round((p.probabilities[pos2] ?? 0) * 100)}%
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : <Empty />}
          </Panel>

          <Panel title="Scarcity — remaining by pos">
            {scarcity ? (
              <div className="space-y-2">
                {Object.entries(scarcity.scarcity).map(([b, grid]) => (
                  <div key={b}>
                    <div className="text-[10px] uppercase tracking-wider text-text-dim mb-1">{BAND_LABEL[b] ?? b}</div>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(grid)
                        .sort((a, b2) => b2[1] - a[1])
                        .slice(0, 12)
                        .map(([p, n]) => (
                          <span key={p} className="text-[11px] px-1.5 py-0.5 rounded bg-bg-hover text-text-muted font-mono">
                            {p} {n}
                          </span>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : <Empty />}
          </Panel>

          <Panel title="Last 10 Picks">
            {state?.last_10_picks?.length ? (
              <div className="space-y-1">
                {[...state.last_10_picks].reverse().map((p) => (
                  <div key={p.overall_pick} className="flex gap-2 text-[11px] text-text-muted">
                    <span className="font-mono text-text-dim w-10">#{p.overall_pick}</span>
                    <span className="w-10 text-text-dim">fr {p.franchise_id}</span>
                    <span className={`truncate ${p.devy_pending ? "italic text-text-dim" : ""}`}
                          title={p.devy_pending
                            ? "Devy slot taken -- MFL still shows a placeholder; the name appears once the owner renames it"
                            : undefined}>
                      {p.devy_pending && "⏳ "}
                      {p.player_name ?? p.player_id ?? `mfl:${p.mfl_player_id}`}
                    </span>
                  </div>
                ))}
              </div>
            ) : <div className="text-xs text-text-dim">No picks yet.</div>}
          </Panel>
        </aside>
      </div>
    </div>
  );
}

function Panel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-bg-card p-3">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">{title}</h2>
        {hint && <span className="text-[10px] text-text-dim">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

const Empty = () => <div className="text-xs text-text-dim">—</div>;

function BoardTable({
  rows, league, showSurvival, survival, onSaved,
}: {
  rows: BoardPlayer[];
  league: string;
  showSurvival: boolean;
  survival: Record<string, SurvivalResponse>;
  onSaved: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-bg-elevated text-text-dim">
            <tr>
              <Th className="w-10">#</Th>
              <Th>Player</Th>
              <Th className="w-12">Pos</Th>
              <Th className="w-16">Band</Th>
              <Th className="w-14 text-right">ADP</Th>
              <Th className="w-16 text-right">WAR</Th>
              <Th className="w-14 text-right">Mock</Th>
              <Th className="w-14 text-right">Class</Th>
              <Th className="w-20 text-right">Composite</Th>
              {showSurvival && <Th className="w-16 text-right">Survive</Th>}
              <Th className="w-14">Tier</Th>
              <Th className="w-40">Note</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <Row key={p.player_id} p={p} idx={i + 1} league={league}
                   showSurvival={showSurvival} surv={survival[p.player_id]} onSaved={onSaved} />
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={12} className="px-3 py-6 text-center text-text-dim">No players match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const Th = ({ children, className }: { children?: React.ReactNode; className?: string }) => (
  <th className={cn('px-2 py-2 text-left font-medium uppercase tracking-wider text-[10px]', className)}>{children}</th>
);
const Td = ({ children, className }: { children?: React.ReactNode; className?: string }) => (
  <td className={cn('px-2 py-1.5 align-middle', className)}>{children}</td>
);

function Row({
  p, idx, league, showSurvival, surv, onSaved,
}: {
  p: BoardPlayer; idx: number; league: string;
  showSurvival: boolean; surv?: SurvivalResponse; onSaved: () => void;
}) {
  const [tier, setTier] = useState<string>(p.tier == null ? '' : String(p.tier));
  const [note, setNote] = useState<string>(p.note ?? '');
  const [saving, setSaving] = useState(false);
  useEffect(() => { setTier(p.tier == null ? '' : String(p.tier)); setNote(p.note ?? ''); },
    [p.player_id, p.tier, p.note]);

  const commit = async () => {
    setSaving(true);
    try {
      await saveTier(league, p.player_id, tier === '' ? null : Number(tier), note || null);
      onSaved();
    } finally { setSaving(false); }
  };

  const pct = surv?.survival_pct_rounded;
  return (
    <tr className="border-t border-border-subtle hover:bg-bg-hover/50">
      <Td className="text-text-dim font-mono">{idx}</Td>
      <Td>
        <span className="text-text">{p.full_name ?? p.player_id}</span>
        {p.resolution_status === 'synthetic' && (
          <span className="ml-1.5 text-[9px] px-1 rounded border border-border text-text-dim" title="no linked stats record">
            syn
          </span>
        )}
      </Td>
      <Td className="font-mono text-text-muted">{p.position ?? '—'}</Td>
      <Td>
        <span className={cn('text-[9px] px-1.5 py-0.5 rounded border', BAND_CLASS[p.pool_band])}>
          {BAND_LABEL[p.pool_band] ?? p.pool_band}
        </span>
      </Td>
      <Td className="text-right font-mono text-text-muted">{num(p.adp, 2)}</Td>
      <Td className="text-right font-mono text-text-muted">{p.war_value == null ? '—' : p.war_value.toFixed(0)}</Td>
      <Td className="text-right font-mono text-text-muted">{p.mock_rank ?? '—'}</Td>
      <Td className="text-right font-mono text-text-dim">{p.draft_class ?? '—'}</Td>
      <Td className="text-right font-mono text-accent">{num(p.composite_rank, 1)}</Td>
      {showSurvival && (
        <Td className="text-right font-mono">
          {pct == null ? <span className="text-text-dim">—</span> : (
            <span className={cn(pct >= 70 ? 'text-accent' : pct >= 40 ? 'text-warn' : 'text-error')}>
              {pct}%
            </span>
          )}
        </Td>
      )}
      <Td>
        <input
          value={tier}
          onChange={(e) => setTier(e.target.value.replace(/[^0-9]/g, ''))}
          onBlur={commit}
          className="w-10 bg-bg-elevated border border-border rounded px-1 py-0.5 text-xs text-text focus:outline-none focus:border-accent/50"
          placeholder="—"
        />
      </Td>
      <Td>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={commit}
          className={cn(
            'w-full bg-bg-elevated border border-border rounded px-1.5 py-0.5 text-xs text-text focus:outline-none focus:border-accent/50',
            saving && 'opacity-50',
          )}
          placeholder="note…"
        />
      </Td>
    </tr>
  );
}
