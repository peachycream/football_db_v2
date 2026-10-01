// NFL team colors for categorical color encoding on scatter plots.
//
// Six teams (LV, CHI, HOU, NE, TEN, SEA) originally used primary colors so
// dark they were nearly invisible against the dashboard's #0a0e1a background
// (contrast ratios of 1.07 - 1.22:1). For those teams we swap to the
// brand's official secondary color, which is also iconic and recognizable:
//   LV  black -> silver         (Raiders silver)
//   CHI dark navy -> orange     (Bears orange)
//   HOU dark navy -> red        (Texans battle red - brightened to #E22329)
//   NE  navy -> patriot red     (Patriots red)
//   TEN dark navy -> light blue (Titans light blue)
//   SEA navy -> action green    (Seahawks action green)
//
// Note: HOU red is close to KC red in hue (both teams own a similar red
// historically); the chart legend and hover tooltip disambiguate. NE red
// is also close to KC; swap NE to '#7B96C4' (Patriots nautical blue) if
// confusable in your typical comparisons.

export const TEAM_COLORS: Record<string, string> = {
  ARI: '#97233F',
  ATL: '#A71930',
  BAL: '#241773',
  BUF: '#00338D',
  CAR: '#0085CA',
  CHI: '#C83803',  // was '#0B162A' — pivoted to Bears orange
  CIN: '#FB4F14',
  CLE: '#311D00',
  DAL: '#003594',
  DEN: '#FB4F14',
  DET: '#0076B6',
  GB:  '#203731',
  HOU: '#E22329',  // was '#03202F' — pivoted to brighter Texans red
  IND: '#002C5F',
  JAX: '#006778',
  KC:  '#E31837',
  LA:  '#003594',
  LAC: '#0080C6',
  LV:  '#A5ACAF',  // was '#000000' — pivoted to Raiders silver
  MIA: '#008E97',
  MIN: '#4F2683',
  NE:  '#C60C30',  // was '#002244' — pivoted to Patriots red
  NO:  '#D3BC8D',
  NYG: '#0B2265',
  NYJ: '#125740',
  PHI: '#004C54',
  PIT: '#FFB612',
  SEA: '#69BE28',  // was '#002244' — pivoted to Seahawks action green
  SF:  '#AA0000',
  TB:  '#D50A0A',
  TEN: '#4B92DB',  // was '#0C2340' — pivoted to Titans light blue
  WAS: '#5A1414',
};

// Marker stroke color used on every dot. Picking something lighter than the
// chart bg (#0a0e1a) means even dark-team fills (CLE brown, NYG navy, BAL
// purple, IND navy, WAS maroon, GB forest, BUF navy) still have a visible
// edge against the background. Tuned to be subtle on bright fills.
export const MARKER_STROKE = '#3a4358';

const FALLBACK_COLOR = '#7a8399';

export function teamColor(team: string | null | undefined): string {
  if (!team) return FALLBACK_COLOR;
  // Multi-team season string: "LV, NYJ" -> color by first team
  const first = String(team).split(',')[0].trim();
  return TEAM_COLORS[first] ?? FALLBACK_COLOR;
}
