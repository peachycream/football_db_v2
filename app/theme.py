"""Server-side companion to static/theme.css.

Blueprints that build HTML in Python need the same colour decisions the
stylesheet encodes. This module holds the *mappings* only -- never a hex
value. Every function returns a var() reference, so theme.css stays the
single source of truth and a hue change still takes one edit there.

POS_TOKEN mirrors the POS table in static/theme.js. They are the same
mapping expressed for two runtimes; change them together.

Import as:  import theme
"""

# Finer position codes fold onto their group hue. DT and S have their own
# lighter shades so a stacked bar keeps every segment tellable apart.
POS_TOKEN = {
    "QB": "qb", "RB": "rb", "WR": "wr", "TE": "te",
    "DL": "dl", "DE": "dl", "DT": "dt",
    "LB": "lb",
    "DB": "db", "CB": "db", "S": "s", "SAF": "s",
}


def pos_var(position, fallback="var(--tx-mut)"):
    """CSS var() for a position's hue, e.g. 'WR' -> 'var(--wr)'.

    Unknown or missing positions get the muted text token rather than a
    guess -- an invented colour would read as a real encoding.
    """
    key = POS_TOKEN.get(str(position or "").strip().upper())
    return f"var(--{key})" if key else fallback


def delta_var(value, zero="var(--tx-mut)"):
    """CSS var() for a signed value on the diverging scale.

    Positive -> --div-pos, negative -> --div-neg, zero -> muted. The sign
    glyph should always be rendered too: hue is reinforcement here, never
    the only channel (see the note in theme.css).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return zero
    if v > 0:
        return "var(--div-pos)"
    if v < 0:
        return "var(--div-neg)"
    return zero


def delta_span(value, fmt="{:+,.1f}", weight=600, size=None):
    """A signed value rendered on the diverging scale, sign always shown."""
    style = f"color:{delta_var(value)};font-weight:{weight}"
    if size:
        style += f";font-size:{size}"
    try:
        text = fmt.format(float(value))
    except (TypeError, ValueError):
        text = str(value)
    return f'<span style="{style}">{text}</span>'


# ─────────────────────────────────────────────────────────────────────────
# PER-TOOL ACCENT
#
# Four family accents rather than one per tool -- see the note in theme.css
# for why nineteen hues would be noise rather than navigation. Because both
# nav renderers already draw the active chip with var(--accent), overriding
# that one property per page lights the chip and the page chrome together.
#
# Set PER_APP_ACCENT = False to put the entire app back on one accent; that
# is the only change needed to undo this.
# ─────────────────────────────────────────────────────────────────────────

PER_APP_ACCENT = True

# Longest matching prefix wins, so /viz/draft beats /viz/. Order here is for
# readability only -- accent_for() sorts by length.
APP_ACCENT = {
    "/":             "app-explore",
    "/viz/":         "app-explore",
    "/viz/player":   "app-explore",
    "/viz/offense":  "app-explore",
    "/viz/defense":  "app-explore",

    "/audit/":       "app-league",
    "/scouting/":    "app-league",
    "/ownership/":   "app-league",
    "/viz/draft":    "app-league",
    "/viz/matchups": "app-league",
    "/viz/draft-grades": "app-league",
    "/draft/":       "app-league",
    "/matchups/":    "app-league",

    "/projections/": "app-model",
    "/aethersight/": "app-model",
    # Aliases for the same tools, so they resolve to the same family rather
    # than falling through to the default (app.py and trinity_viewer both
    # register these paths).
    "/trinity/":        "app-model",
    "/trinity-viewer/": "app-model",
    "/coverage/":    "app-model",
    "/tendencies/":  "app-model",
    "/def-align/":   "app-model",
    "/cfb-devy/":    "app-model",

    "/glossary/":    "app-ref",
    "/playerids/":   "app-ref",
    "/snaps/":       "app-ref",
    "/reader/":      "app-ref",
}

DEFAULT_ACCENT = "app-explore"


def accent_token(path):
    """Family accent token for a route, by longest matching prefix.

    "/" only matches exactly, mirroring how both nav renderers decide which
    chip is active -- otherwise every path would match it.
    """
    p = str(path or "/")
    best = None
    for prefix, token in APP_ACCENT.items():
        if prefix == "/":
            if p == "/":
                best = best or ("/", token)
            continue
        if p == prefix or p.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, token)
    return best[1] if best else DEFAULT_ACCENT


def accent_for(path):
    """CSS var() for a route's family accent, e.g. 'var(--app-league)'."""
    return f"var(--{accent_token(path)})"


def accent_style(path):
    """A <style> block re-pointing --accent at the route's family accent.

    Emit it AFTER the base stylesheet so it wins. Returns '' when per-app
    accents are switched off, so callers need no conditional of their own.
    """
    if not PER_APP_ACCENT:
        return ""
    # Override the CHANNELS, not just the colour: theme.css derives --accent
    # from --accent-rgb and theme.js reads the channels for alpha, so setting
    # only one of the two leaves the JS bridge on a stale accent.
    tok = accent_token(path)
    return (f"<style>:root{{--accent-rgb:var(--{tok}-rgb);"
            f"--accent:rgb(var(--accent-rgb))}}</style>")
