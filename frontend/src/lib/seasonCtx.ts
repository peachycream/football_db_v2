// seasonCtx -- the season (and week) each page opens on.
//
// The values are DERIVED SERVER-SIDE from the data and injected into the shell
// as `window.__SEASON_CTX__` by app.py's _serve_viz_shell, exactly as the theme
// accent and the freshness line are. The derivation therefore lives in ONE
// Python module (app/season_ctx.py) and this bundle carries no copy of it --
// so next September's rollover needs no vite build, and the two cannot drift.
//
// >>> THE FALLBACKS BELOW ARE NOT DEFAULTS, THEY ARE A LAST RESORT. <<<
// They exist only for the case where the tag is absent -- opening the built
// index.html without Flask in front of it. Every one is a floor: a season list
// that stops short is visibly short, whereas a plausible-looking wrong year is
// exactly the failure this whole change is undoing. They are deliberately NOT
// kept current; if you find yourself editing them, the injection is broken and
// that is the thing to fix.

export type SeasonSurface =
  | 'player' | 'offense' | 'defense' | 'matchups' | 'coverage' | 'scatter'
  | 'snaps_off' | 'snaps_def';

type SurfaceCtx = {
  season: number;
  week: number | null;
  next_week: number | null;
  seasons: number[];
};

declare global {
  interface Window { __SEASON_CTX__?: Partial<Record<SeasonSurface, SurfaceCtx>>; }
}

// Last-resort floors. See the note above -- these are not maintained.
const FALLBACK: Record<string, { season: number; seasons: number[] }> = {
  player:   { season: 2025, seasons: [2025, 2024, 2023, 2022, 2021] },
  offense:  { season: 2025, seasons: [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016] },
  defense:  { season: 2025, seasons: [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016] },
  matchups: { season: 2025, seasons: [2025, 2024, 2023] },
  coverage: { season: 2025, seasons: [2025, 2024, 2023, 2022, 2021] },
  scatter:  { season: 2025, seasons: [2025, 2024, 2023, 2022, 2021] },
};

function ctx(surface: SeasonSurface): Partial<SurfaceCtx> | null {
  try {
    return window.__SEASON_CTX__?.[surface] ?? null;
  } catch {
    return null;
  }
}

/** The season this surface opens on. */
export function defaultSeason(surface: SeasonSurface): number {
  const v = ctx(surface)?.season;
  return typeof v === 'number' ? v : (FALLBACK[surface]?.season ?? 2025);
}

/** Every season this surface has data for, newest first. */
export function seasonList(surface: SeasonSurface): number[] {
  const v = ctx(surface)?.seasons;
  return Array.isArray(v) && v.length ? v : (FALLBACK[surface]?.seasons ?? []);
}

/**
 * The week to open on.
 *
 * `'played'`   the last week with rows -- for anything showing results.
 * `'upcoming'` the week after it -- for anything projecting forward, like the
 *              Matchup Tool. Clamped server-side so a closed season cannot
 *              return a week that never existed.
 */
export function defaultWeek(surface: SeasonSurface,
                            kind: 'played' | 'upcoming' = 'played'): number | null {
  const c = ctx(surface);
  const v = kind === 'upcoming' ? c?.next_week : c?.week;
  return typeof v === 'number' ? v : null;
}

/** The two most recent seasons, newest last -- the Scatter Explorer's default
 *  selection. Falls back to one season rather than inventing a neighbour. */
export function recentSeasons(surface: SeasonSurface, n = 2): number[] {
  return seasonList(surface).slice(0, n).reverse();
}
