import { useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/useDebounce';
import { Field, Popover, Button } from '@/components/ui/primitives';
import SnapTrend from '@/components/SnapTrend';
import TrinityTrend from '@/components/TrinityTrend';
import RouteTree from '@/components/RouteTree';
import QbPassingProfile from '@/components/QbPassingProfile';
import RbRushingProfile from '@/components/RbRushingProfile';
import IdpAlignmentProfile from '@/components/IdpAlignmentProfile';
import {
  dashboardSearch,
  dashboardPlayers,
  dashboardHeader,
  dashboardLeagues,
  dashboardTiles,
  dashboardAvailableSeasons,
  BUCKETS,
  NFL_TEAMS,
  DASH_SEASONS,
  type DashSearchHit,
  type DashPlayerListItem,
  type DashHeader,
  type DashLeague,
  type DashTile,
  type DashTilesResponse,
} from '@/lib/dashboardApi';
import { readPlayerNavFromLocation, navigateToOrigin, type NavOrigin } from '@/lib/playerNav';
import { defaultSeason } from '@/lib/seasonCtx';

const DEFAULT_LEAGUE = 'default';
// Derived, not a literal: see lib/seasonCtx.ts.
const DEFAULT_SEASON = defaultSeason('player');
// Optional content scale. 1 = full size (visuals sized to fill the viewport at
// 100%). Drop to 0.9 / 0.85 only if your browser window is short enough that the
// grid + viz would otherwise scroll.
const ZOOM = 1;

export default function PlayerDashboard() {
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebounce(query, 200);

  const [posFilter, setPosFilter] = useState<string | null>(null);
  const [teamFilter, setTeamFilter] = useState<string | null>(null);
  const [season, setSeason] = useState<number>(DEFAULT_SEASON);
  const [leagueId, setLeagueId] = useState<string>(DEFAULT_LEAGUE);

  const [leagues, setLeagues] = useState<DashLeague[]>([]);
  const [hits, setHits] = useState<(DashSearchHit | DashPlayerListItem)[]>([]);
  const [listOpen, setListOpen] = useState(false);

  const [selected, setSelected] = useState<DashSearchHit | null>(null);
  const [header, setHeader] = useState<DashHeader | null>(null);
  const [headerLoading, setHeaderLoading] = useState(false);
  const [tiles, setTiles] = useState<DashTilesResponse | null>(null);
  const [tilesLoading, setTilesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [origin, setOrigin] = useState<NavOrigin | null>(null);

  const comboRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [capturing, setCapturing] = useState(false);
  const searchTok = useRef(0);
  const headerTok = useRef(0);
  const tilesTok = useRef(0);
  const deepLinkNameNeeded = useRef(false);

  // Deep-link entry (a PlayerLink click from another screen) ----------------
  // Reads ?player=&origin_view=&origin_label=[&origin_state=] on mount only.
  // Absence of these params is fully supported (direct open, refresh,
  // existing entry points) — origin stays null, season stays DEFAULT_SEASON,
  // selection stays driven entirely by the search combobox as before.
  useEffect(() => {
    const { playerId, origin: o } = readPlayerNavFromLocation();
    if (o) setOrigin(o);
    if (!playerId) return;
    deepLinkNameNeeded.current = true;
    setSelected({
      player_id: playerId,
      full_name: null,
      position: null,
      team: null,
      side: null,
      bucket: null,
    });
    dashboardAvailableSeasons(playerId)
      .then((r) => { if (r.most_recent != null) setSeason(r.most_recent); })
      .catch(() => { /* no data found — DEFAULT_SEASON (already the initial state) stands */ });
  }, []);

  // Leagues (selector) ------------------------------------------------------
  useEffect(() => {
    dashboardLeagues()
      .then((ls) =>
        setLeagues([
          { league_id: 'default', label: 'Default (PPR)', enabled: true },
          ...ls.filter((l) => l.league_id !== 'default'),
        ]),
      )
      .catch(() =>
        setLeagues([
          { league_id: 'default', label: 'Default (PPR)', enabled: true },
        ]),
      );
  }, []);

  // Search / browse ---------------------------------------------------------
  useEffect(() => {
    const tok = ++searchTok.current;
    const q = debouncedQuery.trim();

    const run = async () => {
      try {
        if (q.length >= 2) {
          let res = await dashboardSearch(q, 25);
          if (posFilter) res = res.filter((r) => r.bucket === posFilter);
          if (teamFilter) res = res.filter((r) => r.team === teamFilter);
          if (tok === searchTok.current) setHits(res);
        } else if (posFilter || teamFilter) {
          const res = await dashboardPlayers({
            league_id: leagueId, season,
            bucket: posFilter, team: teamFilter, limit: 100,
          });
          if (tok === searchTok.current) setHits(res);
        } else {
          if (tok === searchTok.current) setHits([]);
        }
      } catch (e) {
        if (tok === searchTok.current) {
          setHits([]);
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    };
    run();
  }, [debouncedQuery, posFilter, teamFilter, leagueId, season]);

  // Close the results panel on outside click
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (comboRef.current && !comboRef.current.contains(e.target as Node)) {
        setListOpen(false);
      }
    };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  // Header readout for the selected player ----------------------------------
  useEffect(() => {
    if (!selected) { setHeader(null); return; }
    const tok = ++headerTok.current;
    setHeaderLoading(true);
    setError(null);
    dashboardHeader(selected.player_id, season, leagueId)
      .then((h) => {
        if (tok !== headerTok.current) return;
        setHeader(h);
        if (deepLinkNameNeeded.current) {
          deepLinkNameNeeded.current = false;
          setQuery(h.full_name ?? '');
          // The deep-link placeholder set in the mount effect only has
          // player_id — position/team/side/bucket start null and, unlike a
          // normal search pick (onPick sets the full DashSearchHit at once),
          // nothing else ever filled them in. RouteTree/QbPassingProfile/
          // RbRushingProfile/IdpAlignmentProfile/SnapTrend all key off
          // selected.bucket/selected.side (not header's), so those panels
          // silently never rendered for ANY deep-linked player regardless
          // of position — this fills selected in from the header response,
          // the same shape a real search pick would have produced.
          setSelected((prev) => (prev ? {
            ...prev,
            full_name: h.full_name,
            position: h.position,
            team: h.team,
            side: h.side,
            bucket: h.bucket,
          } : prev));
        }
      })
      .catch((e) => {
        if (tok === headerTok.current) {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => { if (tok === headerTok.current) setHeaderLoading(false); });
  }, [selected, season, leagueId]);

  // Tiles for the selected player -------------------------------------------
  useEffect(() => {
    if (!selected) { setTiles(null); return; }
    const tok = ++tilesTok.current;
    setTilesLoading(true);
    dashboardTiles(selected.player_id, season, leagueId)
      .then((t) => { if (tok === tilesTok.current) setTiles(t); })
      .catch((e) => {
        if (tok === tilesTok.current) {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => { if (tok === tilesTok.current) setTilesLoading(false); });
  }, [selected, season, leagueId]);

  const onPick = (h: DashSearchHit) => {
    setSelected(h);
    setQuery(h.full_name ?? '');
    setListOpen(false);
  };

  // Screen capture — renders the dashboard content to a PNG. html2canvas-pro is
  // loaded at click time from a CDN (no bundled dependency / npm install) and
  // handles modern CSS color funcs. Best at ZOOM = 1 (CSS zoom isn't captured).
  const capture = async () => {
    const node = contentRef.current;
    if (!node || capturing) return;
    setCapturing(true);
    try {
      const mod: any = await import(
        /* @vite-ignore */ 'https://esm.sh/html2canvas-pro@1.5.11'
      );
      const html2canvas = mod.default ?? mod;
      const canvas = await html2canvas(node, {
        backgroundColor: 'var(--bg)',
        scale: 2,
        useCORS: true,
      });
      const link = document.createElement('a');
      link.download = `${selected?.player_id ?? 'player'}_${season}_dashboard.png`;
      link.href = canvas.toDataURL('image/png');
      link.click();
    } catch (e) {
      setError(`Capture failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCapturing(false);
    }
  };

  const leagueLabel = useMemo(
    () => leagues.find((l) => l.league_id === leagueId)?.label ?? leagueId,
    [leagues, leagueId],
  );

  return (
    <div className="flex flex-col h-full bg-bg text-text">
      {/* Top bar */}
      <header className="h-12 shrink-0 border-b border-border px-4 flex items-center justify-between bg-bg-card">
        <div className="flex items-center gap-3">
          <a
            href="/"
            className="text-xs text-text-muted hover:text-text transition-colors"
          >
            ← Home
          </a>
          {origin && (
            <button
              type="button"
              onClick={() => navigateToOrigin(origin)}
              className="text-xs text-text-muted hover:text-text transition-colors"
            >
              ← Back to {origin.label}
            </button>
          )}
          <h1 className="text-sm font-semibold text-text">Player Dashboard</h1>
          <span className="text-[10px] uppercase tracking-wider text-text-dim">
            Football DB
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={capture}
            disabled={!selected || capturing}
            className="text-xs text-text-muted hover:text-text transition-colors
                       border border-border rounded-md px-2 py-1
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {capturing ? 'Capturing…' : '⤓ Capture PNG'}
          </button>
          <a
            href="/viz/"
            className="text-xs text-text-muted hover:text-text transition-colors"
          >
            Scatter Explorer →
          </a>
        </div>
      </header>

      {/* Body: left filter sidebar + main content */}
      <div className="flex-1 min-h-0 flex">
        <aside className="shrink-0 w-64 border-r border-border bg-bg-card/40 p-4
                          flex flex-col gap-4">
        {/* Search combobox (resolver-backed) */}
        <Field label="Search player" className="w-full order-5">
          <div className="relative" ref={comboRef}>
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setListOpen(true); }}
              onFocus={() => setListOpen(true)}
              placeholder="Type a name…"
              className={cn(
                'h-8 w-full rounded-md bg-bg-elevated border border-border px-2.5',
                'text-sm text-text placeholder:text-text-dim',
                'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/20',
              )}
            />
            {listOpen && hits.length > 0 && (
              <div className="absolute z-30 mt-1 max-h-72 w-full overflow-auto
                              rounded-md bg-bg-card border border-border shadow-xl shadow-black/50">
                {hits.map((h) => (
                  <button
                    key={h.player_id}
                    type="button"
                    onClick={() => onPick(h)}
                    className="w-full text-left px-2.5 py-1.5 text-sm flex items-center
                               justify-between hover:bg-bg-elevated transition-colors"
                  >
                    <span className="text-text truncate">{h.full_name}</span>
                    <span className="text-text-dim text-xs ml-2 shrink-0">
                      {h.bucket}{h.team ? ` · ${h.team}` : ''}
                      {'fantasy_total' in h && h.fantasy_total != null
                        ? ` · ${h.fantasy_total}` : ''}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </Field>

        <Field label="Position" className="w-full order-2">
          <SelectMenu
            value={posFilter}
            placeholder="Any"
            options={[{ value: null, label: 'Any' },
              ...BUCKETS.map((b) => ({ value: b, label: b }))]}
            onChange={(v) => { setPosFilter(v); setListOpen(true); }}
          />
        </Field>

        <Field label="Team" className="w-full order-3">
          <SelectMenu
            value={teamFilter}
            placeholder="Any"
            options={[{ value: null, label: 'Any' },
              ...NFL_TEAMS.map((t) => ({ value: t, label: t }))]}
            onChange={(v) => { setTeamFilter(v); setListOpen(true); }}
          />
        </Field>

        <Field label="Season" className="w-full order-1">
          <SelectMenu
            value={String(season)}
            options={DASH_SEASONS.map((s) => ({ value: String(s), label: String(s) }))}
            onChange={(v) => setSeason(Number(v))}
          />
        </Field>

        <Field label="League" className="w-full order-4">
          <SelectMenu
            value={leagueId}
            options={leagues.map((l) => ({
              value: l.league_id,
              label: l.label,
              disabled: !l.enabled,
            }))}
            onChange={(v) => setLeagueId(v ?? DEFAULT_LEAGUE)}
            placeholder={leagueLabel}
          />
        </Field>
      </aside>

        {/* Header readout + tile area */}
        <main className="flex-1 min-h-0 overflow-auto p-5">
        {error && <div className="mb-3 text-xs text-error">⨯ {error}</div>}

        {!selected ? (
          <div className="h-full flex items-center justify-center border border-dashed
                          border-border rounded-lg">
            <p className="text-text-muted text-sm max-w-sm text-center">
              Search by name, or pick a Position / Team to browse the top players,
              then select one to load the dashboard.
            </p>
          </div>
        ) : (
          <div style={{ zoom: ZOOM } as React.CSSProperties}>
            <div ref={contentRef} className="mx-auto w-full max-w-[1600px] flex flex-col gap-4">
              <PlayerHeaderCard header={header} loading={headerLoading} />

              {/* left: the position-specific vertical visual (RouteTree for
                  receivers, QbPassingProfile for QBs, RbRushingProfile for
                  RBs — mutually exclusive, same slot; neither renders yet
                  for IDP, that's Phase 3), filling the same footprint the
                  3x3 tile square used to. right: the 9 tiles (back to a
                  square 3x3, not the wide strip) stacked above snap trend.
                  items-stretch: now BOTH columns carry real, comparably-tall
                  content (tiles+snap stacked vs. the position visual), so
                  stretching them to match is correct here -- unlike before,
                  when stretch was forcing a short standalone SnapTrend to
                  match a much taller tile column with nothing to fill the
                  gap. */}
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 xl:items-stretch">
                <div className="min-w-0 flex flex-col">
                  <RouteTree
                    playerId={selected.player_id}
                    season={season}
                    bucket={selected.bucket}
                  />
                  <QbPassingProfile
                    playerId={selected.player_id}
                    season={season}
                    bucket={selected.bucket}
                    leagueId={leagueId}
                  />
                  <RbRushingProfile
                    playerId={selected.player_id}
                    season={season}
                    bucket={selected.bucket}
                  />
                  <IdpAlignmentProfile
                    playerId={selected.player_id}
                    season={season}
                    bucket={selected.bucket}
                    leagueId={leagueId}
                  />
                </div>
                <div className="min-w-0 flex flex-col gap-4">
                  <TileGrid data={tiles} loading={tilesLoading} />
                  <SnapTrend
                    playerId={selected.player_id}
                    season={season}
                    side={selected.side}
                  />
                  <TrinityTrend
                    playerId={selected.player_id}
                    season={season}
                    bucket={selected.bucket}
                  />
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header readout — the player is the headline; PPG is the hero figure, the
// rest are supporting reads with hairline separators.
// ---------------------------------------------------------------------------
function PlayerHeaderCard({
  header, loading,
}: { header: DashHeader | null; loading: boolean }) {
  const stats: { label: string; value: string; hero?: boolean }[] = [
    { label: 'Fantasy PPG', value: fmt(header?.fantasy_ppg), hero: true },
    { label: 'Season', value: fmt(header?.fantasy_total) },
    { label: 'Games', value: header?.games != null ? String(header.games) : '—' },
  ];
  return (
    <div className="rounded-xl border border-border bg-bg-card overflow-hidden">
      <div className="flex flex-col sm:flex-row sm:items-stretch">
        {/* Identity */}
        <div className="flex-1 min-w-0 p-4 sm:p-5">
          <div className="flex items-center gap-2">
            <h2 className="text-2xl font-semibold text-text truncate tracking-tight">
              {header?.full_name ?? (loading ? 'Loading…' : 'Select a player')}
            </h2>
            {header?.bucket && (
              <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5
                               py-0.5 rounded bg-accent/15 text-accent border border-accent/40">
                {header.bucket}
              </span>
            )}
          </div>
          <div className="text-xs text-text-dim mt-1 tracking-wide">
            {[
              header?.position,
              header?.team,
              header?.season,
              header?.age != null ? `${header.age} yo` : null,
              header?.draft_year != null ? `Draft ${header.draft_year}` : null,
            ]
              .filter(Boolean).join('  ·  ') || '\u00A0'}
            {header?.scoring_label && (
              <span className="ml-2 text-text-dim/70">· {header.scoring_label}</span>
            )}
          </div>
        </div>

        {/* Stat cluster */}
        <div className="flex items-stretch border-t sm:border-t-0 sm:border-l border-border">
          {stats.map((s, i) => (
            <div
              key={s.label}
              className={cn(
                'flex flex-col justify-center px-5 py-3 sm:py-4 text-right',
                i > 0 && 'border-l border-border',
              )}
            >
              <div className={cn(
                'font-semibold tabular-nums leading-none',
                s.hero ? 'text-3xl text-accent' : 'text-xl text-text',
              )}>
                {s.value}
              </div>
              <div className="text-[10px] uppercase tracking-wider text-text-dim mt-1.5">
                {s.label}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function fmt(n: number | null | undefined): string {
  return n == null ? '—' : String(n);
}

// ---------------------------------------------------------------------------
// Tile grid — one dense grid. ★ tiles lead and carry an accent rule; the
// percentile reads as a color-scaled fill bar along the bottom of every tile,
// so strengths and gaps are scannable down the whole grid.
// ---------------------------------------------------------------------------
function TileGrid({
  data, loading,
}: { data: DashTilesResponse | null; loading: boolean }) {
  if (loading && !data) {
    return <div className="mt-4 text-text-dim text-sm">Loading tiles…</div>;
  }
  if (!data) return null;

  // ★ first, then the rest — but all in one grid so nothing stretches.
  const ordered = [...data.tiles].sort((a, b) => {
    const sa = a.star && !a.blank ? 0 : 1;
    const sb = b.star && !b.blank ? 0 : 1;
    return sa - sb || a.n - b.n;
  });

  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-text-dim mb-2">
        {data.bucket} · pool {data.pool_size}{data.games != null ? ` · ${data.games} G` : ''}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {ordered.map((t) => <TileCard key={t.n} t={t} />)}
      </div>
    </div>
  );
}

function TileCard({ t }: { t: DashTile }) {
  if (t.blank) {
    return (
      <div className="aspect-square rounded-lg border border-dashed border-border/50
                      bg-bg-card/30 p-3 flex flex-col">
        <Eyebrow label={t.label} />
        <div className="flex-1 flex items-center justify-center text-text-dim/60 text-xs">
          not yet tracked
        </div>
      </div>
    );
  }
  const star = !!t.star;
  return (
    <div className={cn(
      'group relative aspect-square rounded-lg bg-bg-card p-3 flex flex-col',
      'transition-colors hover:bg-bg-elevated/40',
      star
        ? 'border border-accent/30 border-t-2 border-t-accent/70'
        : 'border border-border',
    )}>
      <div className="flex items-start justify-between gap-1">
        <Eyebrow label={t.label} accent={star} />
        {t.warn && (
          <span title="known caveat — see spec notes" className="text-warn text-[11px]">⚠</span>
        )}
      </div>

      <div className="flex-1 flex flex-col justify-center">
        <div className="text-3xl font-semibold tabular-nums text-text leading-none tracking-tight">
          {t.display ?? 'n/a'}
        </div>
        {t.sub && <div className="text-[11px] text-text-dim mt-1.5 truncate">{t.sub}</div>}
        {t.per_game && (
          <div className="text-[10px] uppercase tracking-wider text-text-dim mt-1.5">
            per game
          </div>
        )}
      </div>

      {t.percentile != null && <PercentileBar pct={t.percentile} />}
    </div>
  );
}

function Eyebrow({ label, accent }: { label: string; accent?: boolean }) {
  return (
    <span className={cn(
      'text-[10px] uppercase tracking-wider font-semibold truncate',
      accent ? 'text-accent/90' : 'text-text-dim',
    )}>
      {label}
    </span>
  );
}

// Percentile as a color-scaled fill bar, labeled so the number reads clearly
// as a percentile rank within the position pool.
function PercentileBar({ pct }: { pct: number }) {
  const hue = Math.max(0, Math.min(120, pct * 1.2));
  const fill = `hsl(${hue} 70% 50%)`;
  return (
    <div className="mt-2" title={`${pct}th percentile within the position pool`}>
      <div className="relative h-1 rounded-full bg-bg-elevated overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, backgroundColor: fill }}
        />
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span className="text-[9px] uppercase tracking-wider text-text-dim">percentile</span>
        <span className="text-[11px] font-semibold tabular-nums" style={{ color: fill }}>
          {pct}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Minimal select built on the shared Popover primitive
// ---------------------------------------------------------------------------
interface Opt { value: string | null; label: string; disabled?: boolean }
function SelectMenu({
  value, options, onChange, placeholder,
}: {
  value: string | null;
  options: Opt[];
  onChange: (v: string | null) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value);
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      align="left"
      trigger={
        <Button variant="outline" size="sm" className="w-full justify-between">
          <span className="truncate">{current?.label ?? placeholder ?? 'Select'}</span>
          <span className="text-text-dim ml-1">▾</span>
        </Button>
      }
    >
      <div className="max-h-72 overflow-auto py-1">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            disabled={o.disabled}
            onClick={() => { if (!o.disabled) { onChange(o.value); setOpen(false); } }}
            className={cn(
              'w-full text-left px-3 py-1.5 text-sm transition-colors',
              o.value === value ? 'text-accent' : 'text-text-muted hover:text-text',
              o.disabled
                ? 'opacity-30 cursor-not-allowed'
                : 'hover:bg-bg-elevated',
            )}
          >
            {o.label}{o.disabled ? '  (locked)' : ''}
          </button>
        ))}
      </div>
    </Popover>
  );
}
