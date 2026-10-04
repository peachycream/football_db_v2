"""Page chrome for the v2 app. BASE_STYLE is v1's league_audit.BASE_STYLE,
copied verbatim (colour lives in static/theme.css; REBUILD_DESIGN §6: the colour
system is carried over as is)."""
import html

from . import theme

NAV_LINKS = [("/ownership/", "OWNERSHIP"), ("/viz/player", "PLAYER"), ("/viz/offense", "TEAM OFFENSE"),
             ("/viz/defense", "TEAM DEFENSE"), ("/matchups/", "MATCHUPS"), ("/matchup/", "MATCHUP CARD")]

# The hub at "/" (v1's landing page; the React pages' "Hub" link points here). Only ported apps.
HUB_APPS = [
    ("/ownership/", "Ownership", "Who owns whom across the MFL and Sleeper leagues; wishlist"),
    ("/viz/player", "Player Dashboard", "Single-player tiles, QB zones, RB lanes, IDP alignment, snap trend"),
    ("/viz/offense", "Team Offense Environment", "Pace, EPA, personnel splits, percentile-ranked, trend over time"),
    ("/viz/defense", "Team Defense Environment", "EPA, pass rush, coverage, run defense allowed, scheme"),
    ("/matchups/", "Matchup Tool", "Which defenses allow the most fantasy points to each position"),
    ("/matchup/", "Matchup Card", "Review the weekly Matchup of the Week card before anything is posted"),
]


def hub_html() -> str:
    cards = "".join(f'<a href="{h}" class="card"><div class="card-title">{html.escape(t)}</div>'
                    f'<div class="card-desc">{html.escape(d)}</div></a>' for h, t, d in HUB_APPS)
    return page_shell("Hub", f'<div class="grid-3">{cards}</div>', active="/")

BASE_STYLE = """
<style>
/* Colour lives in /static/theme.css — add new hues there, not here. */
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--tx);
  font-family: var(--f-body);
  min-height: 100vh;
}
/* A whisper of the page's family accent in the ground (see theme.py
   PER_APP_ACCENT). 4% at the top only -- enough to feel, not enough to
   tint a screenshot or fight a chart. Fixed so it never scrolls away. */
body::before {
  content: "";
  position: fixed;
  inset: 0 0 auto 0;
  height: 420px;
  pointer-events: none;
  z-index: 0;
  background: radial-gradient(120% 100% at 50% 0%,
              rgb(var(--accent-rgb) / .04) 0%, transparent 70%);
}
.header, .content { position: relative; z-index: 1; }
.header {
  background: var(--surf-2);
  border-bottom: 1px solid var(--edge);
  padding: 14px 24px;
  display: flex;
  align-items: center;
  gap: 24px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.logo {
  font-size: 1.4rem;
  font-weight: 900;
  color: var(--accent);
  letter-spacing: 3px;
  text-decoration: none;
}
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--accent);
  margin-left: auto;
  box-shadow: 0 0 8px var(--accent);
}
.content { padding: 24px; }
.badge {
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 2px 7px;
  border-radius: 4px;
  text-transform: uppercase;
}
.badge-idp   { background: color-mix(in srgb, var(--tag-idp) 16%, transparent); color: var(--tag-idp); border: 1px solid var(--tag-idp); }
.badge-sf    { background: color-mix(in srgb, var(--tag-sf)  16%, transparent); color: var(--tag-sf);  border: 1px solid var(--tag-sf); }
.badge-bb    { background: color-mix(in srgb, var(--tag-bb)  16%, transparent); color: var(--tag-bb);  border: 1px solid var(--tag-bb); }
.badge-lu    { background: color-mix(in srgb, var(--tag-lu)  16%, transparent); color: var(--tag-lu);  border: 1px solid var(--tag-lu); }
.card {
  background: var(--surf-1);
  border: 1px solid var(--edge);
  border-radius: 8px;
  padding: 20px 24px;
  transition: border-color var(--dur-2) var(--ease),
              transform var(--dur-1) var(--ease),
              box-shadow var(--dur-2) var(--ease);
  cursor: pointer;
  text-decoration: none;
  display: block;
  color: inherit;
}
.card {
  box-shadow: var(--shadow-1);
}
.card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: var(--shadow-2);
}
.card-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--tx);
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}
.card-desc {
  font-size: 0.78rem;
  color: var(--tx-mut);
  margin-bottom: 12px;
}
.card-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.card-actions {
  margin-top: 14px;
  display: flex;
  gap: 8px;
}
.btn {
  display: inline-block;
  padding: 7px 14px;
  border-radius: 5px;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  cursor: pointer;
  text-decoration: none;
  border: none;
  transition: opacity 0.15s;
}
.btn:hover { opacity: 0.85; }
.btn { transition: opacity var(--dur-1) var(--ease), box-shadow var(--dur-1) var(--ease); }
.btn-primary:hover { box-shadow: var(--shadow-2); }
.btn-primary { background: var(--accent); color: var(--accent-ink); }
.btn-secondary { background: var(--surf-3); color: var(--tag-sf); border: 1px solid var(--edge); }
.btn-danger { background: color-mix(in srgb, var(--bad) 12%, transparent); color: var(--bad); border: 1px solid color-mix(in srgb, var(--bad) 34%, transparent); }
.grid-3 {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.section-title {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.15em;
  color: var(--tx-mut);
  text-transform: uppercase;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--edge-soft);
}
.page-title {
  font-size: 1.6rem;
  font-weight: 900;
  letter-spacing: 0.04em;
  color: var(--tx);
  margin-bottom: 6px;
}
.page-sub {
  font-size: 0.85rem;
  color: var(--tx-mut);
  margin-bottom: 24px;
}
.alert {
  background: var(--surf-2);
  border: 1px solid var(--edge);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 0.82rem;
  color: var(--tx-mut);
  margin-bottom: 20px;
}
.alert-warn { border-left-color: var(--mid); }
.alert-err  { border-left-color: var(--bad); }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
/* NOT sticky: the page header is itself sticky and its height is NOT fixed
   -- 19 nav links wrap differently by viewport (measured 81px at desktop
   width), so any fixed offset here would leave a gap or an overlap at some
   widths. Revisit only if the header gets a fixed height. */
th {
  text-align: left;
  padding: 10px 12px;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--tx-mut);
  border-bottom: 1px solid var(--edge);
  background: var(--surf-2);
}
td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--edge-soft);
  color: var(--tx);
}
tr:hover td { background: var(--surf-2); }
.tag-idp  { color: var(--tag-idp); }
.tag-sf   { color: var(--tag-sf); }
.tag-bb   { color: var(--tag-bb); }
.tag-lu   { color: var(--tag-lu); }
.mono { font-family: var(--f-mono); font-size: 0.8rem; color: var(--accent); }

/* Keyboard focus. :focus-visible rather than :focus so the ring appears for
   keyboard users without firing on every mouse click -- which is the reason
   focus rings usually get removed. Nothing here had one before. */
a:focus-visible, button:focus-visible, [tabindex]:focus-visible,
input:focus-visible, select:focus-visible, textarea:focus-visible,
.card:focus-visible, .btn:focus-visible {
  outline: none;
  box-shadow: var(--ring);
  border-radius: 5px;
}

/* Honour the OS setting. Every transition above is decorative. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  .card:hover { transform: none; }
}
</style>
"""


def nav_html(active: str) -> str:
    links = ""
    for href, label in NAV_LINKS:
        is_active = active == href or active.startswith(href)
        color = "var(--accent)" if is_active else "var(--tx-mut)"
        border = "border-bottom:2px solid var(--accent);" if is_active else ""
        links += (f'<a href="{href}" style="color:{color};text-decoration:none;font-size:0.78rem;'
                  f'font-weight:{"700" if is_active else "400"};padding:4px 0;letter-spacing:0.06em;'
                  f'margin-right:18px;{border}">{label}</a>')
    return links


def page_shell(title: str, content: str, active: str = "/") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{html.escape(title)} — football_db v2</title>
<link rel="stylesheet" href="/static/theme.css">
<script src="/static/theme.js"></script>
{BASE_STYLE}
{theme.accent_style(active)}
</head>
<body>
<div class="header">
  <a href="/" class="logo">FOOTBALL DB</a>
  {nav_html(active)}
  <span class="status-dot"></span>
</div>
<div class="content">
{content}
</div>
</body>
</html>"""
