import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Draft Grades (DRAFT_GRADER_BUILD.md Phase 6).
//
// Cascading league -> conference (multi-conf leagues only) -> division -> team.
// Division grade table (sortable, default score desc), expandable team card
// with pick-by-pick grades, needs before/after, and the generated narrative.
//
// Written while the drafts were live and ~round 1 in; as of 2026-09-18 they are
// essentially complete (is_final=1 on 243 of 262 team rows). The "Graded
// through N of M picks" banner is NON-DISMISSIBLE (build §6.2) -- it is the
// single most important element for not misleading anyone into reading a
// 1-of-17 rolling grade as final, and it reads the live counts, so it was
// right in both states.
//
// Data comes from the read-only draft_grader_bp API. No chart library; bars are
// plain divs. Selectors are native <select> for keyboard access.
// ---------------------------------------------------------------------------

type Division = {
  id: string; name: string;
  conference_id: string | null; conference_name: string | null;
  graded_teams: number;
};
type League = {
  league: string; league_id: string; name: string;
  multi_conference: boolean;
  conferences: { id: string; name: string }[];
  divisions: Division[];
  graded_teams: number; picks_made: number; picks_total: number;
  teams_final: number; is_final: boolean;
};
type Components = {
  value_component: number; need_component: number;
  construction_component: number; scarcity_component: number;
  redundancy_penalty: number;
};
type Team = {
  franchise_id: string; name: string;
  division_id: string; division_name: string;
  conference_name: string | null;
  archetype: string | null; archetype_conf: number | null;
  prior_rank: number | null; roster_age_w: number | null;
  picks_made: number; picks_total: number;
  total_score: number | null; letter: string; is_final: boolean;
  components: Components;
};
type Grades = {
  league: string; name: string; division: string | null;
  picks_made: number; picks_total: number; teams_final: number;
  team_count: number; is_final: boolean; teams: Team[];
};
type Pick = {
  round: number; pick: number; overall: number; player: string | null;
  pos: string | null; board_rank: number | null; slot_delta: number | null;
  value_delta: number | null; bpa_delta: number | null; need_fit: number | null;
  scarcity_capture: number | null; redundancy: number | null;
  pick_score: number | null; verdict: string;
};
type TeamDetail = {
  franchise: {
    id: string; name: string; division_name: string;
    conference_name: string | null; archetype: string | null;
    archetype_conf: number | null; prior_rank: number | null;
    roster_age_w: number | null;
  };
  grade: {
    total_score: number | null; letter: string; picks_made: number;
    picks_total: number; is_final: boolean; components: Components;
  };
  picks: Pick[];
  needs_before: { pos: string; need_score: number; gap: number }[];
  needs_after: { pos: string; need_score: number }[];
  positions_addressed: string[];
  narrative: string | null;
  narrative_model: string | null;
};

// ---- Season Recap types (end-of-year: draft-time grade + realized started-pts) ----
type RecapTeam = {
  franchise_id: string; name: string;
  division_id: string; division_name: string;
  conference_id: string | null; conference_name: string | null;
  picks: number;
  draft_letter: string; draft_z: number | null;
  season_letter: string; season_z: number | null;
  delta: number | null; started_pts: number | null; class_prod: number | null;
};
type Recap = {
  league: string; name: string; season: number; division: string | null;
  team_count: number; teams: RecapTeam[];
};
type RecapPick = {
  overall: number; round: number; rookie_slot: number;
  player: string | null; pos: string | null;
  consensus_rank: number | null; market_surplus: number | null;
  total_pts: number | null; started_pts: number | null; started_any: number | null;
  weeks_rostered: number; weeks_started: number; traded: boolean;
  games_out: number; weeks_benched: number;
  outcome: string; outcome_label: string; outcome_tone: 'good' | 'bad' | 'neutral';
};
type RecapTeamDetail = {
  season: number;
  franchise: { id: string; name: string; division_name: string };
  grade: {
    draft_letter: string; draft_z: number | null;
    season_letter: string; season_z: number | null; delta: number | null;
    picks: number; started_pts: number | null; class_prod: number | null;
  };
  picks: RecapPick[];
  narrative: string | null;
  narrative_model: string | null;
};

const j = <T,>(u: string): Promise<T> => fetch(u).then((r) => r.json());

// minimal, safe markdown: **bold** + `>` blockquote + blank-line paragraphs.
// Builds React nodes (no dangerouslySetInnerHTML). Enough for the recaps, which
// are plain prose with bold labels and a leading blockquote caveat.
function renderInline(text: string, keyBase: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  parts.forEach((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) {
      out.push(<strong key={`${keyBase}-b${i}`} className="text-text font-semibold">{p.slice(2, -2)}</strong>);
    } else if (p) {
      out.push(<span key={`${keyBase}-t${i}`}>{p}</span>);
    }
  });
  return out;
}
function MarkdownLite({ md }: { md: string }) {
  const blocks = md.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  return (
    <div className="space-y-2">
      {blocks.map((b, i) => {
        const quote = b.startsWith('>');
        const clean = b.replace(/^>\s?/gm, '').replace(/\n/g, ' ');
        return (
          <p key={i} className={cn('leading-relaxed',
            quote ? 'text-warn border-l-2 border-warn/40 pl-3' : 'text-text-muted')}>
            {renderInline(clean, `p${i}`)}
          </p>
        );
      })}
    </div>
  );
}

function readParams() {
  const p = new URLSearchParams(window.location.search);
  return { league: p.get('league') || '', division: p.get('division') || '',
           franchise: p.get('franchise') || '' };
}

// verdict -> color class + whether it's a "good" verdict
// >>> EVERY ENCODING BELOW USES A FIXED SEMANTIC TOKEN, NEVER --accent. <<<
// Rule (1) of the colour system: the accent is CHROME and never a data value.
// It is re-pointed per tool family (theme.py PER_APP_ACCENT), and on this
// page's family (app-league) it resolves to rgb(122 162 255) -- byte-identical
// to --info. So `text-accent` and `text-info` rendered THE SAME COLOUR, and
// the grade ladder collapsed: A, B+ and B were indistinguishable on screen.
//
// It looked fine on the branch this came from, which predates the per-app
// accent: back then --accent was spring green and B's blue was clearly
// different. The violation only became VISIBLE once the accent moved.
const VERDICT_STYLE: Record<string, string> = {
  steal: 'bg-good/15 text-good border-good/30',
  value: 'bg-good/10 text-good border-good/25',
  fair: 'bg-bg-hover text-text-muted border-border',
  'slight reach': 'bg-warn/10 text-warn border-warn/30',
  reach: 'bg-error/10 text-error border-error/30',
};
const LETTER_STYLE: Record<string, string> = {
  'A+': 'text-good', A: 'text-good', 'A-': 'text-good',
  'B+': 'text-info', B: 'text-info', 'B-': 'text-info',
  'C+': 'text-warn', C: 'text-warn', 'C-': 'text-warn', D: 'text-error',
  F: 'text-error',
};
const OUTCOME_STYLE: Record<'good' | 'bad' | 'neutral', string> = {
  good: 'bg-good/15 text-good border-good/30',
  bad: 'bg-error/10 text-error border-error/30',
  neutral: 'bg-bg-hover text-text-muted border-border',
};
// Δ (season − draft z): + = overperformed the draft, − = underperformed
function deltaStyle(d: number | null): string {
  if (d == null) return 'text-text-muted';
  if (d >= 0.5) return 'text-good';
  if (d <= -0.5) return 'text-error';
  return 'text-text-muted';
}

// verdict chip text carries the SIGN in words, not just color (build §6.2)
function verdictLabel(v: string, slot: number | null): string {
  const cap = v.charAt(0).toUpperCase() + v.slice(1);
  if (slot == null) return cap;
  if (slot > 0) return `${cap} +${slot}`;      // taken earlier than board rank
  if (slot < 0) return `${cap} −${Math.abs(slot)}`;
  return `${cap} 0`;
}

function readView(): 'grades' | 'recap' {
  const p = new URLSearchParams(window.location.search);
  return p.get('view') === 'recap' ? 'recap' : 'grades';
}

export default function DraftGrades() {
  const init = readParams();
  const [view, setView] = useState<'grades' | 'recap'>(readView());
  const [leagues, setLeagues] = useState<League[]>([]);
  const [recapLeagues, setRecapLeagues] = useState<League[]>([]);
  const [recapSeason, setRecapSeason] = useState<number | null>(null);
  const [bootErr, setBootErr] = useState<string | null>(null);
  const [league, setLeague] = useState(init.league);
  const [conf, setConf] = useState('');
  const [division, setDivision] = useState(init.division);
  const [grades, setGrades] = useState<Grades | null>(null);
  const [recap, setRecap] = useState<Recap | null>(null);
  const [recapDetail, setRecapDetail] = useState<RecapTeamDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(init.franchise);
  const [detail, setDetail] = useState<TeamDetail | null>(null);
  const [sortKey, setSortKey] = useState<'score' | 'name' | 'made'>('score');
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const [preview, setPreview] = useState<{ open: boolean; data: any } | null>(null);

  // bootstrap: both the live grades leagues and the recap leagues
  useEffect(() => {
    j<{ leagues: League[] }>('/api/draft/leagues')
      .then((d) => {
        setLeagues(d.leagues);
        setLeague((l) => l || (d.leagues[0]?.league ?? ''));
      })
      .catch((e) => setBootErr(String(e)));
    j<{ leagues: League[]; season: number }>('/api/draft/recap/leagues')
      .then((d) => { setRecapLeagues(d.leagues); setRecapSeason(d.season); })
      .catch(() => { /* recap optional */ });
  }, []);

  // which league list feeds the selectors for the active view
  const displayLeagues = view === 'recap' ? recapLeagues : leagues;

  const activeLeague = useMemo(
    () => displayLeagues.find((l) => l.league === league) || null,
    [displayLeagues, league]);

  // divisions shown, filtered by conference for multi-conf leagues
  const shownDivisions = useMemo(() => {
    if (!activeLeague) return [];
    let divs = activeLeague.divisions;
    if (activeLeague.multi_conference && conf) {
      divs = divs.filter((d) => d.conference_id === conf);
    }
    return divs;
  }, [activeLeague, conf]);

  // when league changes, reset conf/division to sensible defaults
  useEffect(() => {
    if (!activeLeague) return;
    if (activeLeague.multi_conference) {
      setConf((c) => c || activeLeague.conferences[0]?.id || '');
    } else {
      setConf('');
    }
  }, [activeLeague]);

  useEffect(() => {
    // pick a default division with graded teams once divisions are known
    if (!activeLeague) return;
    const pool = shownDivisions;
    if (division && pool.some((d) => d.id === division)) return;
    const firstGraded = pool.find((d) => d.graded_teams > 0) || pool[0];
    setDivision(firstGraded ? firstGraded.id : '');
  }, [activeLeague, shownDivisions]); // eslint-disable-line

  // when entering recap view, if the selected league has no recap data, jump to
  // the first league that does (only 60856/2025 is populated at first).
  useEffect(() => {
    if (view !== 'recap' || recapLeagues.length === 0) return;
    const cur = recapLeagues.find((l) => l.league === league);
    if (!cur || cur.graded_teams === 0) {
      const first = recapLeagues.find((l) => l.graded_teams > 0);
      if (first && first.league !== league) {
        setLeague(first.league); setConf(''); setDivision(''); setExpanded('');
      }
    }
  }, [view, recapLeagues]); // eslint-disable-line

  // fetch GRADES (live pre-draft) on league+division change
  useEffect(() => {
    if (view !== 'grades') return;
    if (!league || !division) { setGrades(null); return; }
    setLoading(true);
    j<Grades>(`/api/draft/grades?league=${league}&division=${division}`)
      .then(setGrades)
      .catch(() => setGrades(null))
      .finally(() => setLoading(false));
  }, [view, league, division]);

  // fetch RECAP (end-of-year) on league+division change
  useEffect(() => {
    if (view !== 'recap') return;
    if (!league || !division) { setRecap(null); return; }
    setLoading(true);
    j<Recap>(`/api/draft/recap?league=${league}&division=${division}`)
      .then(setRecap)
      .catch(() => setRecap(null))
      .finally(() => setLoading(false));
  }, [view, league, division]);

  // fetch team detail when a row is expanded (per view)
  useEffect(() => {
    if (!expanded || !league) { setDetail(null); setRecapDetail(null); return; }
    if (view === 'recap') {
      j<RecapTeamDetail>(`/api/draft/recap/team/${league}/${expanded}`)
        .then(setRecapDetail).catch(() => setRecapDetail(null));
    } else {
      j<TeamDetail>(`/api/draft/team/${league}/${expanded}`)
        .then(setDetail).catch(() => setDetail(null));
    }
  }, [view, expanded, league]);

  // keep URL in sync
  useEffect(() => {
    const u = new URLSearchParams();
    if (view === 'recap') u.set('view', 'recap');
    if (league) u.set('league', league);
    if (division) u.set('division', division);
    if (expanded) u.set('franchise', expanded);
    window.history.replaceState(null, '', `${window.location.pathname}?${u}`);
  }, [view, league, division, expanded]);

  const sortedTeams = useMemo(() => {
    if (!grades) return [];
    const arr = [...grades.teams];
    arr.sort((a, b) => {
      let d = 0;
      if (sortKey === 'score') d = (a.total_score ?? 0) - (b.total_score ?? 0);
      else if (sortKey === 'name') d = a.name.localeCompare(b.name);
      else if (sortKey === 'made') d = a.picks_made - b.picks_made;
      return d * sortDir;
    });
    return arr;
  }, [grades, sortKey, sortDir]);

  const toggleSort = useCallback((k: 'score' | 'name' | 'made') => {
    if (k === sortKey) setSortDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(k); setSortDir(k === 'name' ? 1 : -1); }
  }, [sortKey]);

  const openPreview = useCallback(() => {
    fetch('/api/draft/discord/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league, division }),
    }).then((r) => r.json()).then((d) => setPreview({ open: true, data: d }));
  }, [league, division]);

  if (bootErr) {
    return <div className="min-h-screen bg-bg text-error p-6 text-sm">
      Failed to load: {bootErr}</div>;
  }

  const rollingText = grades
    ? (grades.is_final
        ? `Final — all ${grades.team_count} teams complete`
        : `Rolling — graded through ${grades.picks_made} of ${grades.picks_total} picks in this division (${grades.teams_final}/${grades.team_count} teams final)`)
    : '';

  return (
    <div className="min-h-screen bg-bg text-text">
      {/* header */}
      <header className="h-12 border-b border-border px-4 flex items-center gap-3 bg-bg-card sticky top-0 z-30">
        <a href="/" className="text-xs text-text-muted hover:text-text transition-colors">← Home</a>
        <h1 className="text-sm font-semibold">Draft Grades</h1>
        <div className="flex items-center gap-1 ml-2 p-0.5 rounded bg-bg-elevated border border-border">
          {(['grades', 'recap'] as const).map((v) => (
            <button
              key={v}
              onClick={() => { setView(v); setExpanded(''); }}
              className={cn('text-xs px-2.5 py-1 rounded transition-colors',
                view === v ? 'bg-accent/20 text-accent font-medium'
                           : 'text-text-muted hover:text-text')}>
              {v === 'grades' ? 'Pre-Draft Grades' : 'Season Recap'}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-4 text-xs">
          <a href="/viz/draft" className="text-text-muted hover:text-text transition-colors">Draft Board →</a>
          <a href="/ownership/" className="text-text-muted hover:text-text transition-colors">Ownership →</a>
        </div>
      </header>

      {/* selectors */}
      <div className="border-b border-border bg-bg-card/60 px-4 py-3 flex flex-wrap items-end gap-3 sticky top-12 z-20">
        <Selector label="League" value={league} onChange={(v) => { setLeague(v); setConf(''); setDivision(''); setExpanded(''); }}>
          {leagues.map((l) => <option key={l.league} value={l.league}>{l.name}</option>)}
        </Selector>
        {activeLeague?.multi_conference && (
          <Selector label="Conference" value={conf} onChange={(v) => { setConf(v); setDivision(''); setExpanded(''); }}>
            {activeLeague.conferences.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Selector>
        )}
        <Selector label="Division" value={division} onChange={(v) => { setDivision(v); setExpanded(''); }}>
          {shownDivisions.map((d) => (
            <option key={d.id} value={d.id}>{d.name} ({d.graded_teams})</option>
          ))}
        </Selector>
        {view === 'grades' && (
          <button
            onClick={openPreview}
            disabled={!grades || grades.team_count === 0}
            className="ml-auto text-xs px-3 py-1.5 rounded border border-border bg-bg-elevated hover:bg-bg-hover disabled:opacity-40 transition-colors">
            Preview Discord digest
          </button>
        )}
        {view === 'recap' && recapSeason && (
          <span className="ml-auto text-[11px] text-text-dim self-center">
            End-of-year recap · {recapSeason} class
          </span>
        )}
      </div>

      {/* NON-DISMISSIBLE rolling banner (grades view only) */}
      {view === 'grades' && grades && (
        <div className={cn(
          'px-4 py-2 text-xs font-medium border-b flex items-center gap-2',
          grades.is_final
            ? 'bg-good/10 text-good border-good/25'
            : 'bg-warn/10 text-warn border-warn/25')}>
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
          {rollingText}
        </div>
      )}

      {/* recap method note */}
      {view === 'recap' && (
        <div className="px-4 py-2 text-[11px] text-text-muted border-b border-border bg-bg-card/40">
          <b className="text-text-muted">Draft grade</b> = market value captured vs draft slot ·
          <b className="text-text-muted"> Season grade</b> = points the drafter actually STARTED ·
          <b className="text-text-muted"> Δ</b> = over/under-performance vs draft billing.
          90-man dynasty rosters mean most rookies are stashes — the season grade rewards immediate lineup impact.
        </div>
      )}

      <div className="max-w-5xl mx-auto px-4 py-5">
        {loading && <div className="text-text-muted text-sm py-8 text-center">Loading…</div>}

        {/* ---------- SEASON RECAP view ---------- */}
        {view === 'recap' && !loading && (!recap || recap.team_count === 0) && (
          <div className="text-text-muted text-sm py-8 text-center">
            No recap data for this league yet. Populated so far: TINO NCAA (2025).
          </div>
        )}
        {view === 'recap' && !loading && recap && recap.team_count > 0 && (
          <RecapTable
            recap={recap} expanded={expanded} setExpanded={setExpanded}
            detail={recapDetail} />
        )}

        {/* ---------- PRE-DRAFT GRADES view ---------- */}
        {view === 'grades' && !loading && grades && grades.team_count === 0 && (
          <div className="text-text-muted text-sm py-8 text-center">
            No graded teams in this division yet (no picks made).
          </div>
        )}

        {view === 'grades' && !loading && grades && grades.team_count > 0 && (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-text-dim text-[11px] uppercase tracking-wide border-b border-border">
                <Th onClick={() => toggleSort('name')} active={sortKey === 'name'} dir={sortDir}>Team</Th>
                <th className="text-left py-2 px-2 font-medium">Archetype</th>
                <Th onClick={() => toggleSort('made')} active={sortKey === 'made'} dir={sortDir} className="text-center">Picks</Th>
                <Th onClick={() => toggleSort('score')} active={sortKey === 'score'} dir={sortDir} className="text-right">Score</Th>
                <th className="text-center py-2 px-2 font-medium">Grade</th>
                <th className="w-6" />
              </tr>
            </thead>
            <tbody>
              {sortedTeams.map((t) => {
                const isOpen = expanded === t.franchise_id;
                return (
                  <Fragment key={t.franchise_id}>
                    <tr
                      onClick={() => setExpanded(isOpen ? '' : t.franchise_id)}
                      className={cn('border-b border-border-subtle cursor-pointer hover:bg-bg-hover/50 transition-colors',
                        isOpen && 'bg-bg-hover/40')}>
                      <td className="py-2 px-2">
                        <div className="font-medium">{t.name}</div>
                        <div className="text-[11px] text-text-dim">
                          {t.division_name}{t.prior_rank ? ` · prior #${t.prior_rank}` : ''}
                        </div>
                      </td>
                      <td className="py-2 px-2 text-text-muted capitalize">
                        {t.archetype || '—'}
                        {t.archetype_conf != null && (
                          <span className="text-text-dim text-[11px]"> ({t.archetype_conf.toFixed(2)})</span>
                        )}
                      </td>
                      <td className="py-2 px-2 text-center tabular-nums text-text-muted">
                        {t.picks_made}<span className="text-text-dim">/{t.picks_total}</span>
                        {!t.is_final && <span className="ml-1 text-warn text-[10px]">•</span>}
                      </td>
                      <td className="py-2 px-2 text-right tabular-nums font-semibold">
                        {t.total_score?.toFixed(1)}
                      </td>
                      <td className={cn('py-2 px-2 text-center font-bold', LETTER_STYLE[t.letter] || 'text-text')}>
                        {t.letter}
                      </td>
                      <td className="text-text-dim text-center">{isOpen ? '▾' : '▸'}</td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={6} className="p-0">
                          <TeamCard detail={detail} team={t} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {preview?.open && (
        <PreviewModal data={preview.data} onClose={() => setPreview(null)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function Selector({ label, value, onChange, children }: {
  label: string; value: string; onChange: (v: string) => void; children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-text-dim">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-bg-elevated border border-border rounded px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent min-w-[9rem]">
        {children}
      </select>
    </label>
  );
}

function Th({ children, onClick, active, dir, className }: {
  children: React.ReactNode; onClick: () => void; active: boolean; dir: 1 | -1; className?: string;
}) {
  return (
    <th
      onClick={onClick}
      className={cn('py-2 px-2 font-medium cursor-pointer select-none hover:text-text text-left', className)}>
      {children}
      {active && <span className="ml-1">{dir === -1 ? '↓' : '↑'}</span>}
    </th>
  );
}

function NeedBar({ pos, score, muted }: { pos: string; score: number; muted?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-8 text-[11px] text-text-muted tabular-nums">{pos}</span>
      <div className="flex-1 h-2 rounded-full bg-bg-elevated overflow-hidden">
        <div
          className={cn('h-full rounded-full', muted ? 'bg-text-dim/40' : 'bg-warn/70')}
          style={{ width: `${Math.min(100, score)}%` }} />
      </div>
      <span className="w-8 text-[11px] text-text-dim tabular-nums text-right">{Math.round(score)}</span>
    </div>
  );
}

function TeamCard({ detail, team }: { detail: TeamDetail | null; team: Team }) {
  if (!detail || detail.franchise.id !== team.franchise_id) {
    return <div className="px-4 py-4 text-text-muted text-xs bg-bg-card/40">Loading team…</div>;
  }
  const g = detail.grade;
  return (
    <div className="bg-bg-card/50 border-t border-border px-4 py-4 space-y-4">
      {/* rolling caveat inside the card too */}
      {!g.is_final && (
        <div className="text-[11px] text-warn">
          Provisional — {g.picks_made} of {g.picks_total} picks made.
        </div>
      )}

      {/* components */}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-text-muted">
        <span>value <b className="text-text">{g.components.value_component?.toFixed(2)}</b></span>
        <span>need <b className="text-text">{g.components.need_component?.toFixed(2)}</b></span>
        <span>construction <b className="text-text">{g.components.construction_component?.toFixed(2)}</b></span>
        <span>scarcity <b className="text-text">{g.components.scarcity_component?.toFixed(2)}</b></span>
        <span>redundancy <b className="text-text">{g.components.redundancy_penalty?.toFixed(2)}</b></span>
      </div>

      {/* picks */}
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-dim mb-1">Picks</div>
        <div className="space-y-1">
          {detail.picks.map((p) => (
            <div key={p.overall} className="flex items-center gap-3 text-sm">
              <span className="w-10 text-text-dim tabular-nums text-[12px]">{p.round}.{String(p.pick).padStart(2, '0')}</span>
              <span className="flex-1 truncate">
                {p.player || '—'} <span className="text-text-dim text-[11px]">{p.pos}</span>
                {p.board_rank != null && <span className="text-text-dim text-[11px]"> · brd {p.board_rank}</span>}
              </span>
              <span className={cn('text-[11px] px-2 py-0.5 rounded border', VERDICT_STYLE[p.verdict] || 'border-border text-text-muted')}>
                {verdictLabel(p.verdict, p.slot_delta)}
              </span>
              <span className="w-10 text-right tabular-nums text-text-muted text-[12px]">{p.pick_score?.toFixed(0)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* needs before / after */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-text-dim mb-1">Top needs — pre-draft</div>
          <div className="space-y-1">
            {detail.needs_before.slice(0, 5).map((n) => (
              <NeedBar key={n.pos} pos={n.pos} score={n.need_score} />
            ))}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-text-dim mb-1">Needs remaining</div>
          <div className="space-y-1">
            {detail.needs_after.length === 0
              ? <div className="text-[11px] text-text-dim">All top needs addressed.</div>
              : detail.needs_after.map((n) => (
                <NeedBar key={n.pos} pos={n.pos} score={n.need_score} muted />
              ))}
          </div>
          {detail.positions_addressed.length > 0 && (
            <div className="text-[11px] text-text-dim mt-2">
              Addressed: <span className="text-good">{detail.positions_addressed.join(', ')}</span>
            </div>
          )}
        </div>
      </div>

      {/* narrative */}
      {detail.narrative && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-text-dim mb-1">
            Analyst recap {detail.narrative_model && <span className="normal-case">· {detail.narrative_model}</span>}
          </div>
          <div className="text-sm bg-bg/40 rounded p-3 border border-border-subtle">
            <MarkdownLite md={detail.narrative} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Season Recap table + team card
function RecapTable({ recap, expanded, setExpanded, detail }: {
  recap: Recap; expanded: string; setExpanded: (v: string) => void;
  detail: RecapTeamDetail | null;
}) {
  return (
    <table className="w-full text-sm border-collapse">
      <thead>
        <tr className="text-text-dim text-[11px] uppercase tracking-wide border-b border-border">
          <th className="text-left py-2 px-2 font-medium">Team</th>
          <th className="text-center py-2 px-2 font-medium">Draft</th>
          <th className="text-center py-2 px-2 font-medium">Season</th>
          <th className="text-center py-2 px-2 font-medium">Δ</th>
          <th className="text-right py-2 px-2 font-medium">Started pts</th>
          <th className="w-6" />
        </tr>
      </thead>
      <tbody>
        {recap.teams.map((t) => {
          const isOpen = expanded === t.franchise_id;
          return (
            <Fragment key={t.franchise_id}>
              <tr
                onClick={() => setExpanded(isOpen ? '' : t.franchise_id)}
                className={cn('border-b border-border-subtle cursor-pointer hover:bg-bg-hover/50 transition-colors',
                  isOpen && 'bg-bg-hover/40')}>
                <td className="py-2 px-2">
                  <div className="font-medium">{t.name}</div>
                  <div className="text-[11px] text-text-dim">
                    {t.division_name} · {t.picks} rookie picks
                  </div>
                </td>
                <td className={cn('py-2 px-2 text-center font-bold', LETTER_STYLE[t.draft_letter] || 'text-text')}>
                  {t.draft_letter}
                </td>
                <td className={cn('py-2 px-2 text-center font-bold', LETTER_STYLE[t.season_letter] || 'text-text')}>
                  {t.season_letter}
                </td>
                <td className={cn('py-2 px-2 text-center tabular-nums font-semibold', deltaStyle(t.delta))}>
                  {t.delta == null ? '—' : (t.delta > 0 ? `+${t.delta.toFixed(2)}` : t.delta.toFixed(2))}
                </td>
                <td className="py-2 px-2 text-right tabular-nums font-semibold">
                  {Math.round(t.started_pts ?? 0)}
                  <span className="text-text-dim text-[11px]"> / {Math.round(t.class_prod ?? 0)}</span>
                </td>
                <td className="text-text-dim text-center">{isOpen ? '▾' : '▸'}</td>
              </tr>
              {isOpen && (
                <tr>
                  <td colSpan={6} className="p-0">
                    <RecapTeamCard detail={detail} team={t} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

function RecapTeamCard({ detail, team }: { detail: RecapTeamDetail | null; team: RecapTeam }) {
  if (!detail || detail.franchise.id !== team.franchise_id) {
    return <div className="px-4 py-4 text-text-muted text-xs bg-bg-card/40">Loading team…</div>;
  }
  const g = detail.grade;
  const counts = detail.picks.reduce<Record<string, number>>((m, p) => {
    m[p.outcome] = (m[p.outcome] || 0) + 1; return m;
  }, {});
  const order = [['HIT', 'hits'], ['CONTRIBUTOR', 'contributors'],
    ['SPOT_START', 'spot starts'], ['PRODUCED_NOT_STARTED', 'produced·benched'],
    ['STASH', 'stashes'], ['BUST', 'busts']];
  return (
    <div className="bg-bg-card/50 border-t border-border px-4 py-4 space-y-4">
      {/* summary */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[12px]">
        <span className="text-text-muted">Draft <b className={cn('font-bold', LETTER_STYLE[g.draft_letter])}>{g.draft_letter}</b></span>
        <span className="text-text-muted">Season <b className={cn('font-bold', LETTER_STYLE[g.season_letter])}>{g.season_letter}</b></span>
        <span className="text-text-muted">Δ <b className={cn('font-semibold', deltaStyle(g.delta))}>
          {g.delta == null ? '—' : (g.delta > 0 ? `+${g.delta.toFixed(2)}` : g.delta.toFixed(2))}</b></span>
        <span className="text-text-muted">Started <b className="text-text">{Math.round(g.started_pts ?? 0)}</b> of <b className="text-text">{Math.round(g.class_prod ?? 0)}</b> class pts</span>
      </div>
      {/* outcome counts */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-text-dim">
        {order.map(([k, label]) => counts[k]
          ? <span key={k}>{label}: <b className="text-text-muted">{counts[k]}</b></span>
          : null)}
      </div>
      {/* pick rows */}
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-dim mb-1">
          Rookie picks — started pts vs total production
        </div>
        <div className="space-y-1">
          {detail.picks.map((p) => (
            <div key={p.overall} className="flex items-center gap-3 text-sm">
              <span className="w-10 text-text-dim tabular-nums text-[12px]">
                {p.round}.{String(p.rookie_slot).padStart(2, '0')}
              </span>
              <span className="flex-1 truncate">
                {p.player || '—'} <span className="text-text-dim text-[11px]">{p.pos}</span>
                {p.consensus_rank != null && <span className="text-text-dim text-[11px]"> · cRank {p.consensus_rank}</span>}
                {p.traded && <span className="text-warn text-[10px] ml-1">TRADED</span>}
                {p.games_out > 0 && (
                  <span className="text-warn text-[10px] ml-1" title="weeks ruled Out (injury; may understate IR)">
                    ⛑ missed {p.games_out}
                  </span>
                )}
                {p.weeks_benched > 0 && (
                  <span className="text-warn text-[10px] ml-1" title="weeks benched at the NFL level (snap-share collapse after starting)">
                    🪑 benched {p.weeks_benched}
                  </span>
                )}
              </span>
              <span className="w-24 text-right tabular-nums text-[12px]">
                <b className="text-text">{Math.round(p.started_pts ?? 0)}</b>
                <span className="text-text-dim"> / {Math.round(p.total_pts ?? 0)}</span>
              </span>
              <span className={cn('text-[11px] px-2 py-0.5 rounded border w-36 text-center shrink-0',
                OUTCOME_STYLE[p.outcome_tone])}>
                {p.outcome_label}
              </span>
            </div>
          ))}
        </div>
        <div className="text-[11px] text-text-dim mt-2">
          Left number = points the drafter <b>started</b>; right = total production (any lineup, incl. after trade).
        </div>
      </div>

      {/* generated commentary (draft_recap_narratives) */}
      {detail.narrative && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-text-dim mb-1">
            Analyst recap {detail.narrative_model && <span className="normal-case">· {detail.narrative_model}</span>}
          </div>
          <div className="text-sm bg-bg/40 rounded p-3 border border-border-subtle">
            <MarkdownLite md={detail.narrative} />
          </div>
        </div>
      )}
    </div>
  );
}

function PreviewModal({ data, onClose }: { data: any; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-bg-card border border-border rounded-lg max-w-2xl w-full max-h-[85vh] overflow-auto p-5"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold">Discord digest preview</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text text-sm">✕</button>
        </div>
        <div className="text-[11px] text-warn mb-3">
          {data?.webhook_configured
            ? 'Webhook configured. Posting still runs from the Phase 7 CLI (dry-run default).'
            : 'No webhook configured — posting ships in Phase 7. This is preview only; nothing sends.'}
        </div>
        <div className="space-y-3">
          {(data?.embeds || []).map((e: any, i: number) => (
            <div key={i} className="border border-border-subtle rounded p-3 bg-bg/40">
              <div className="font-medium text-sm">{e.embed.title}</div>
              <div className="text-[12px] text-text-muted mt-1 whitespace-pre-wrap line-clamp-6">{e.embed.description}</div>
              <div className="text-[11px] text-text-dim mt-2">{e.embed.footer?.text}</div>
            </div>
          ))}
          {(!data?.embeds || data.embeds.length === 0) && (
            <div className="text-text-muted text-sm">No teams to preview.</div>
          )}
        </div>
      </div>
    </div>
  );
}
