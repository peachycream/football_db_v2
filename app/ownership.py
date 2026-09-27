# -*- coding: utf-8 -*-
"""/ownership/ — cross-league ownership search, FA browse, wishlist, reverse search.

Ported from v1 app/ownership_search.py (Phase 3). What changed and why:
  * Reads mart_* only (REBUILD_DESIGN §2.2 / hard rule 10). v1 read fantasy_rosters
    and called MFL LIVE for franchise names and conference pools on every page;
    here pools come from MFL's own playerLimitUnit, stored at load time.
  * Players are keyed by gsis_id, not v1 name slugs. A rostered player identity
    cannot resolve (devy) keeps a source key: 'mfl:<league>:<id>' / 'sleeper:<id>'.
  * A pool is FREE while it has fewer owners than its capacity (MFL
    rostersPerPlayer; 55757 allows 2). v1 called a pool free only at 0 owners.
  * Writes touch app_* tables only (the wishlist).
The JS/CSS snippets are v1's, unchanged except that suggestions carry `key`.
"""
import html as _html
import sqlite3
from collections import defaultdict
from urllib.parse import urlencode

from flask import Blueprint, jsonify, request

from fdb import config

from . import theme
from .shell import page_shell

bp = Blueprint("ownership", __name__)

_POS_OPTIONS = ["QB", "RB", "WR", "TE", "K", "DL", "DE", "DT", "LB", "DB", "CB", "S"]
_TEAM_OPTIONS = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
                 "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
                 "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
                 "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS", "FA"]

# ---------------------------------------------------------------- v1 JS/CSS --
_SUGGEST_CSS = r"""
<style>
#own-suggest{position:absolute;top:100%;left:0;right:0;margin-top:4px;
  background:var(--bg);border:1px solid var(--edge);border-radius:6px;z-index:50;
  max-height:340px;overflow-y:auto;display:none;
  box-shadow:0 8px 24px rgba(0,0,0,0.5)}
.own-sg{padding:8px 12px;cursor:pointer;font-size:0.85rem}
.own-sg:hover,.own-sg.sel{background:var(--surf-3)}
</style>
"""

_SUGGEST_JS = r"""
<script>
(function () {
  var inp = document.getElementById('own-q');
  if (!inp) return;
  var box = document.getElementById('own-suggest');
  var form = inp.form;
  var timer = null, items = [], sel = -1;

  function esc(x) {
    var d = document.createElement('span');
    d.textContent = (x == null) ? '' : String(x);
    return d.innerHTML;
  }
  function hide() { box.style.display = 'none'; box.innerHTML = ''; items = []; sel = -1; }
  function choose(key) { inp.value = key; hide(); form.submit(); }
  function paintSel() {
    var nodes = box.children;
    for (var i = 0; i < nodes.length; i++)
      nodes[i].className = 'own-sg' + (i === sel ? ' sel' : '');
  }
  function render(list) {
    if (!list.length) { hide(); return; }
    box.innerHTML = ''; items = list; sel = -1;
    list.forEach(function (s) {
      var d = document.createElement('div');
      d.className = 'own-sg';
      d.innerHTML =
        '<span style="font-weight:600">' + esc(s.name) + '</span> ' +
        '<span style="color:' + TOKENS.pos(s.position) + ';font-weight:700;font-size:0.72rem">' + esc(s.position) + '</span> ' +
        '<span style="color:var(--tx-mut);font-size:0.72rem">' + esc(s.team) + '</span>' +
        '<span class="mono" style="float:right;color:var(--tx-mut);font-size:0.68rem">' + esc(s.key) + '</span>';
      d.onmousedown = function (ev) { ev.preventDefault(); choose(s.key); };
      box.appendChild(d);
    });
    box.style.display = 'block';
  }
  function refresh() {
    var q = inp.value.trim();
    if (q.length < 2) { hide(); return; }
    var pos = (form.querySelector('[name=pos]') || {}).value || '';
    var team = (form.querySelector('[name=team]') || {}).value || '';
    fetch('/api/ownership/suggest?q=' + encodeURIComponent(q) +
          '&pos=' + encodeURIComponent(pos) + '&team=' + encodeURIComponent(team))
      .then(function (r) { return r.json(); })
      .then(function (j) { if (inp.value.trim() === q) render(j.suggestions || []); })
      .catch(function () { hide(); });
  }
  inp.addEventListener('input', function () {
    clearTimeout(timer); timer = setTimeout(refresh, 200);
  });
  inp.addEventListener('keydown', function (e) {
    if (box.style.display !== 'block' || !items.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, items.length - 1); paintSel(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paintSel(); }
    else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); choose(items[sel].key); }
    else if (e.key === 'Escape') { hide(); }
  });
  inp.addEventListener('blur', function () { setTimeout(hide, 150); });
  ['pos', 'team'].forEach(function (n) {
    var el = form.querySelector('[name=' + n + ']');
    if (el) el.addEventListener('change', function () {
      if (inp.value.trim().length >= 2) refresh();
    });
  });
})();
</script>
"""

_WAND_CSS = r"""
<style>
.wand-btn{background:none;border:1px solid var(--edge);border-radius:6px;cursor:pointer;
  font-size:0.95rem;line-height:1;padding:3px 9px;opacity:0.45;vertical-align:middle}
.wand-btn:hover{opacity:0.85;border-color:var(--tag-bb)}
.wand-btn.wished{opacity:1;border-color:var(--tag-bb);background:rgba(185,126,247,0.14);
  box-shadow:0 0 7px rgba(185,126,247,0.35)}
</style>
"""

_WAND_JS = r"""
<script>
document.addEventListener('click', function (e) {
  var b = e.target.closest ? e.target.closest('.wand-btn') : null;
  if (!b) return;
  e.preventDefault();
  e.stopPropagation();
  fetch('/api/wishlist/toggle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({player_id: b.getAttribute('data-pid'),
                          context: b.getAttribute('data-ctx') || ''})
  }).then(function (r) { return r.json(); }).then(function (j) {
    if (!j.ok) return;
    if (j.wished) {
      b.classList.add('wished');
      b.title = 'On wishlist — click to remove';
    } else {
      b.classList.remove('wished');
      b.title = 'Add to draft wishlist';
      if (b.hasAttribute('data-remove-row')) {
        var tr = b.closest('tr');
        if (tr) tr.parentNode.removeChild(tr);
      }
    }
  }).catch(function () {});
});
</script>
"""

_PRIO_JS = r"""
<script>
(function () {
  var timers = {};
  function savePrio(inp) {
    var pid = inp.getAttribute('data-pid');
    var lg = inp.getAttribute('data-league') || '';
    var raw = inp.value.trim();
    var prio = raw === '' ? null : parseInt(raw, 10);
    if (raw !== '' && (isNaN(prio) || prio < 1 || prio > 999)) { flash(inp, false); return; }
    var payload = {player_id: pid, priority: prio};
    if (lg) payload.league_id = lg;
    post('/api/wishlist/priority', payload, inp);
  }
  function saveNote(inp) {
    post('/api/wishlist/note',
         {player_id: inp.getAttribute('data-pid'), note: inp.value}, inp);
  }
  function post(url, payload, inp) {
    fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); })
      .then(function (j) { flash(inp, !!j.ok); })
      .catch(function () { flash(inp, false); });
  }
  function flash(inp, ok) {
    inp.style.borderColor = ok ? 'var(--accent)' : 'var(--bad)';
    setTimeout(function () { inp.style.borderColor = 'var(--edge)'; }, 900);
  }
  function kind(el) {
    if (!el.classList) return null;
    if (el.classList.contains('prio-input')) return 'prio';
    if (el.classList.contains('note-input')) return 'note';
    return null;
  }
  function queue(inp, k) {
    var key = k + ':' + inp.getAttribute('data-pid');
    clearTimeout(timers[key]);
    timers[key] = setTimeout(function () {
      if (k === 'prio') savePrio(inp); else saveNote(inp);
    }, 450);
  }
  document.addEventListener('input', function (e) {
    var k = kind(e.target);
    if (k) queue(e.target, k);
  });
  document.addEventListener('keydown', function (e) {
    var k = kind(e.target);
    if (e.key === 'Enter' && k) {
      e.preventDefault();
      var key = k + ':' + e.target.getAttribute('data-pid');
      clearTimeout(timers[key]);
      if (k === 'prio') savePrio(e.target); else saveNote(e.target);
    }
  });
})();
</script>
"""


# ------------------------------------------------------------------ helpers --
def _db():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _esc(s):
    return _html.escape(str(s if s is not None else ""))


def _pool_label(conf):
    return conf if conf else "League"


def _seasons(conn):
    rows = conn.execute("SELECT DISTINCT season FROM mart_roster_ownership ORDER BY season DESC").fetchall()
    return [r[0] for r in rows]


def _season_arg(conn):
    seasons = _seasons(conn)
    default = seasons[0] if seasons else None
    try:
        season = int(request.args.get("season", default))
    except (TypeError, ValueError):
        season = default
    return seasons, season


def _leagues(conn, season):
    """[{lid: 'mfl:30590', lname, platform}] for the season, ordered by name."""
    return [{"lid": f"{r['platform']}:{r['league_id']}", "lname": r["league_name"], "platform": r["platform"]}
            for r in conn.execute("""SELECT DISTINCT platform, league_id, league_name FROM mart_roster_ownership
                                     WHERE season = ? ORDER BY league_name, league_id""", (season,))]


def _split_lid(lid):
    platform, _, league_id = (lid or "").partition(":")
    return platform, league_id


def _is_wished(conn, key):
    return bool(conn.execute("SELECT 1 FROM mart_wishlist WHERE player_key = ?", (key,)).fetchone())


def _wand(pid, wished, context="", remove_row=False):
    cls = "wand-btn wished" if wished else "wand-btn"
    title = "On wishlist — click to remove" if wished else "Add to draft wishlist"
    rr = ' data-remove-row="1"' if remove_row else ""
    return (f'<button type="button" class="{cls}" data-pid="{_esc(pid)}" '
            f'data-ctx="{_esc(context)}"{rr} title="{_esc(title)}">🪄</button>')


def _resolve_query(conn, q, pos=None, team=None, limit=25):
    """q (name fragment or exact player key) -> [{key, name, position, team, is_devy}].
    pos/team filter the name-fragment branch only; an exact key always resolves.
    Rostered players rank first, then exact-key hits, then name."""
    q, pos, team = (q or "").strip(), (pos or "").strip().upper(), (team or "").strip().upper()
    if not q:
        return []
    rows = conn.execute(
        """SELECT player_key, name, position, position_group, team, n_leagues, is_devy FROM mart_player_search
           WHERE player_key = ?
              OR (name LIKE ?
                  AND (? = '' OR UPPER(COALESCE(position, '')) = ? OR UPPER(COALESCE(position_group, '')) = ?)
                  AND (? = '' OR UPPER(COALESCE(team, 'FA')) = ?))
           ORDER BY (n_leagues > 0) DESC, (player_key = ?) DESC, name
           LIMIT ?""",
        (q, f"%{q}%", pos, pos, pos, team, team, q, limit)).fetchall()
    return [{"key": r["player_key"], "name": r["name"] or r["player_key"], "position": r["position"] or "",
             "team": r["team"] or "", "is_devy": bool(r["is_devy"])} for r in rows]


def _pools(conn, season, platform=None, league_id=None):
    """(platform, league_id) -> {pool_id: (pool_name, capacity)} from the latest snapshot."""
    sql = """SELECT DISTINCT platform, league_id, league_name, pool_id, pool_name, pool_capacity
             FROM mart_roster_ownership WHERE season = ?"""
    args = [season]
    if platform:
        sql += " AND platform = ? AND league_id = ?"
        args += [platform, league_id]
    out = defaultdict(dict)
    names = {}
    for r in conn.execute(sql + " ORDER BY league_name, league_id", args):
        out[(r["platform"], r["league_id"])][r["pool_id"]] = (r["pool_name"], r["pool_capacity"])
        names[(r["platform"], r["league_id"])] = r["league_name"]
    return out, names


def _ownership_for_player(conn, key, season):
    """-> [{full_id, league_name, platform, conferences: [{label, owners:[{team, slot, is_mine}],
    capacity, free}], n_conf, n_free}] for every league with a snapshot this season."""
    pools, names = _pools(conn, season)
    held = defaultdict(list)
    for r in conn.execute("""SELECT platform, league_id, pool_id, franchise_name, slot, is_mine
                             FROM mart_roster_ownership WHERE season = ? AND player_key = ?
                             ORDER BY franchise_name""", (season, key)):
        held[(r["platform"], r["league_id"], r["pool_id"])].append(
            {"team": r["franchise_name"], "slot": r["slot"], "is_mine": bool(r["is_mine"])})
    results = []
    for (platform, league_id), plist in pools.items():
        confs, n_free = [], 0
        for pool_id, (pool_name, cap) in sorted(plist.items(), key=lambda kv: (kv[1][0] or "")):
            owners = held.get((platform, league_id, pool_id), [])
            free = len(owners) < (cap or 1)
            n_free += free
            confs.append({"label": pool_name or "", "owners": owners, "capacity": cap, "free": free})
        results.append({"full_id": f"{platform}:{league_id}", "league_name": names[(platform, league_id)],
                        "platform": platform, "conferences": confs, "n_conf": len(confs), "n_free": n_free})
    return results


def _browse_free_agents(conn, lid, conf_sel, pos, team, season, include_unrostered=False, limit=300):
    """FA browse: every fantasy-relevant player who is FREE in the selected league
    (or one pool of it). Universe = players rostered in >= 1 league this season
    (the count is the popularity sort), plus - in deep mode - unrostered players
    on a current NFL team. Free = fewer owners than the pool's capacity."""
    platform, league_id = _split_lid(lid)
    pools, _ = _pools(conn, season, platform, league_id)
    plist = pools.get((platform, league_id), {})
    label_of = {pid: (name or "") for pid, (name, _) in plist.items()}
    cap_of = {(name or ""): cap for _, (name, cap) in plist.items()}
    conf_labels = sorted(cap_of)
    n_pools = len(conf_labels)
    if not n_pools:
        return [], [], 0
    if conf_sel and conf_sel not in cap_of:
        conf_sel = ""
    owned = defaultdict(lambda: defaultdict(int))   # key -> pool label -> owners
    for r in conn.execute("""SELECT player_key, pool_id FROM mart_roster_ownership
                             WHERE season = ? AND platform = ? AND league_id = ?""", (season, platform, league_id)):
        owned[r["player_key"]][label_of.get(r["pool_id"], "")] += 1
    wished = {r[0] for r in conn.execute("SELECT player_key FROM mart_wishlist")}
    rows = conn.execute(
        """SELECT player_key, name, position, team, n_leagues FROM mart_player_search
           WHERE (n_leagues > 0 OR (? AND team IS NOT NULL AND team != 'FA' AND gsis_id IS NOT NULL))
             AND (? = '' OR UPPER(COALESCE(position, '')) = ? OR UPPER(COALESCE(position_group, '')) = ?)
             AND (? = '' OR UPPER(COALESCE(team, 'FA')) = ?)""",
        (1 if include_unrostered else 0, pos, pos, pos, team, team)).fetchall()
    out = []
    for r in rows:
        oc = owned.get(r["player_key"], {})
        free_pools = [c for c in conf_labels if oc.get(c, 0) < (cap_of[c] or 1)]
        if conf_sel:
            if conf_sel not in free_pools:
                continue
            free_label = f"FREE in {_pool_label(conf_sel)}"
        else:
            if not free_pools:
                continue
            free_label = "FREE AGENT" if n_pools == 1 else f"free in {len(free_pools)}/{n_pools} pools"
        out.append({"pid": r["player_key"], "name": r["name"] or r["player_key"], "pos": r["position"] or "",
                    "team": r["team"] or "", "n_leagues": r["n_leagues"], "wished": r["player_key"] in wished,
                    "free_label": free_label})
    out.sort(key=lambda x: (-x["n_leagues"], x["pos"], x["name"]))
    return out[:limit], conf_labels, n_pools


def _resolve_team_query(conn, q, season):
    """Reverse search: team or manager name fragment -> distinct franchise names."""
    q = (q or "").strip()
    if not q:
        return []
    by_team = {}
    for r in conn.execute("""SELECT DISTINCT franchise_name, owner_name, platform, league_id FROM mart_roster_ownership
                             WHERE season = ? AND (franchise_name LIKE ? OR owner_name LIKE ?)""",
                          (season, f"%{q}%", f"%{q}%")):
        e = by_team.setdefault(r["franchise_name"], {"team_name": r["franchise_name"], "manager_name": r["owner_name"],
                                                     "leagues": set()})
        e["leagues"].add(f"{r['platform']}:{r['league_id']}")
    out = [{"team_name": v["team_name"], "manager_name": v["manager_name"], "n_leagues": len(v["leagues"])}
           for v in by_team.values()]
    out.sort(key=lambda x: (-x["n_leagues"], x["team_name"]))
    return out[:25]


def _holdings_for_team(conn, team_name, season):
    results, count = [], defaultdict(int)
    pos_order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}
    slot_rank = {"starter": 0, "roster": 1, "bench": 1, "taxi": 2, "ir": 3}
    leagues = conn.execute("""SELECT DISTINCT platform, league_id, league_name FROM mart_roster_ownership
                              WHERE season = ? AND franchise_name = ? ORDER BY league_name""", (season, team_name)).fetchall()
    for lg in leagues:
        roster = []
        for r in conn.execute("""SELECT o.player_key, o.slot, s.name, s.position FROM mart_roster_ownership o
                                 LEFT JOIN mart_player_search s ON s.player_key = o.player_key
                                 WHERE o.season = ? AND o.platform = ? AND o.league_id = ? AND o.franchise_name = ?""",
                              (season, lg["platform"], lg["league_id"], team_name)):
            count[r["player_key"]] += 1
            roster.append({"player_id": r["player_key"], "name": r["name"] or r["player_key"],
                           "position": r["position"] or "", "slot": r["slot"]})
        roster.sort(key=lambda x: (slot_rank.get(x["slot"], 9), pos_order.get(x["position"], 9), x["name"]))
        results.append({"full_id": f"{lg['platform']}:{lg['league_id']}", "league_name": lg["league_name"],
                        "platform": lg["platform"], "roster": roster, "n_players": len(roster)})
    for lg in results:
        for row in lg["roster"]:
            row["n_leagues_held"] = count[row["player_id"]]
    return results


# ---------------------------------------------------------------- rendering --
def _slot_badge(slot):
    s = (slot or "").lower()
    color = {"starter": "var(--accent)", "bench": "var(--tx-mut)", "roster": "var(--tx-mut)",
             "taxi": "var(--tag-bb)", "ir": "var(--mid)"}.get(s, "var(--tx-mut)")
    return (f'<span style="font-size:0.62rem;font-weight:700;letter-spacing:0.06em;'
            f'text-transform:uppercase;color:{color}">{_esc(s or "—")}</span>')


def _plat_badge(platform):
    return ('<span class="badge badge-bb">SLEEPER</span>' if platform == "sleeper"
            else '<span class="badge badge-lu">MFL</span>')


def _render_results(name, position, season, leagues, key=None, wished=False, is_devy=False):
    total_conf = sum(l["n_conf"] for l in leagues)
    total_free = sum(l["n_free"] for l in leagues)
    wand = ""
    if key and total_free > 0 and not is_devy:
        wand = " " + _wand(key, wished, context=f"player:{season}")
    head = (f'<div class="page-title">{_esc(name)} '
            f'<span style="font-size:0.9rem;color:{theme.pos_var(position)};font-weight:600">{_esc(position)}</span>'
            f'{wand}</div>')
    sub = (f'<div class="page-sub">Ownership across all leagues — {season} season • '
           f'<span style="color:var(--accent);font-weight:700">free in {total_free}</span> '
           f'of {total_conf} pools</div>')
    note = ""
    if is_devy:
        note = ('<div class="alert alert-warn">League-scoped devy player (no NFL identity yet; the CFB phase '
                'will link them). Ownership is shown for the league that lists this id only.</div>')
    if not leagues:
        return head + sub + note + '<div class="alert">No roster snapshots found.</div>'
    blocks = []
    for lg in leagues:
        free_tag = ""
        if lg["n_free"]:
            free_tag = (f'<span style="margin-left:8px;color:var(--accent);font-weight:700;'
                        f'font-size:0.72rem">FREE in {lg["n_free"]}/{lg["n_conf"]}</span>')
        rows = []
        for c in lg["conferences"]:
            label = c["label"] or "League"
            pieces = [f'{_esc(o["team"])}{" ★" if o["is_mine"] else ""} &nbsp;{_slot_badge(o["slot"])}'
                      for o in c["owners"]]
            if not c["owners"]:
                status = '<span style="color:var(--accent);font-weight:700">● FREE AGENT</span>'
            else:
                status = ' &nbsp;|&nbsp; '.join(pieces)
                if c["free"]:  # capacity > owners (rostersPerPlayer 2)
                    status += (f' &nbsp;<span style="color:var(--accent);font-weight:700">● '
                               f'{c["capacity"] - len(c["owners"])} of {c["capacity"]} open</span>')
            rows.append(f'<tr><td style="width:34%"><span class="mono" style="color:var(--info)">{_esc(label)}</span>'
                        f'</td><td>{status}</td></tr>')
        blocks.append(f'<div class="card" style="cursor:default;margin-bottom:14px">'
                      f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
                      f'<span class="card-title" style="margin:0">{_esc(lg["league_name"])}</span>'
                      f'{_plat_badge(lg["platform"])}{free_tag}</div><table>{"".join(rows)}</table></div>')
    return head + sub + note + "".join(blocks)


def _render_holdings(team_name, season, leagues):
    total = sum(l["n_players"] for l in leagues)
    head = f'<div class="page-title">{_esc(team_name)}</div>'
    sub = (f'<div class="page-sub">Holdings across all leagues — {season} season • {len(leagues)} '
           f'league{"s" if len(leagues) != 1 else ""} • {total} total roster spots</div>')
    if not leagues:
        return head + sub + '<div class="alert">No roster snapshots found.</div>'
    blocks = []
    for lg in leagues:
        rows = []
        for p in lg["roster"]:
            overlap = ""
            if p["n_leagues_held"] > 1:
                overlap = (f'<span style="margin-left:8px;font-size:0.62rem;color:var(--mid);font-weight:700;'
                           f'text-transform:uppercase;letter-spacing:0.05em">held in {p["n_leagues_held"]} of your leagues</span>')
            link = f'<a href="/ownership/?{urlencode({"q": p["player_id"], "season": season})}" style="color:var(--tx)">{_esc(p["name"])}</a>'
            rows.append(f'<tr><td style="width:44%">{link}{overlap}</td>'
                        f'<td style="width:14%;color:{theme.pos_var(p["position"])};font-weight:700">{_esc(p["position"])}</td>'
                        f'<td>{_slot_badge(p["slot"])}</td></tr>')
        blocks.append(f'<div class="card" style="cursor:default;margin-bottom:14px">'
                      f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
                      f'<span class="card-title" style="margin:0">{_esc(lg["league_name"])}</span>{_plat_badge(lg["platform"])}'
                      f'<span style="color:var(--tx-mut);font-size:0.72rem">{lg["n_players"]} players</span>'
                      f'</div><table>{"".join(rows)}</table></div>')
    return head + sub + "".join(blocks)


def _options(values, selected, blank=None):
    out = f'<option value="">{blank}</option>' if blank else ""
    return out + "".join(f'<option value="{_esc(v)}"{" selected" if str(v) == str(selected) else ""}>{_esc(v)}</option>'
                         for v in values)


_SEL = 'padding:10px 12px;background:var(--bg);border:1px solid var(--edge);border-radius:6px;color:var(--tx)'


def _search_form(q, season, seasons, pos="", team=""):
    return ('<form method="get" action="/ownership/" autocomplete="off" '
            'style="display:flex;gap:10px;align-items:center;margin-bottom:24px;flex-wrap:wrap">'
            '<div style="flex:1;min-width:240px;position:relative">'
            f'<input name="q" id="own-q" value="{_esc(q)}" placeholder="Player name or id…" autofocus '
            'style="width:100%;box-sizing:border-box;padding:10px 14px;background:var(--bg);'
            'border:1px solid var(--edge);border-radius:6px;color:var(--tx);font-size:0.9rem">'
            '<div id="own-suggest"></div></div>'
            f'<select name="pos" style="{_SEL}">{_options(_POS_OPTIONS, pos, "Any pos")}</select>'
            f'<select name="team" style="{_SEL}">{_options(_TEAM_OPTIONS, team, "Any team")}</select>'
            f'<select name="season" style="{_SEL}">{_options(seasons, season)}</select>'
            '<button class="btn btn-primary" type="submit">SEARCH</button></form>'
            + _SUGGEST_CSS + _SUGGEST_JS)


def _render_candidate_list(cands, season):
    items = []
    for c in cands:
        items.append(f'<a class="card" href="/ownership/?{urlencode({"q": c["key"], "season": season})}" style="margin-bottom:8px">'
                     f'<span class="card-title" style="margin:0">{_esc(c["name"])} '
                     f'<span style="color:{theme.pos_var(c["position"])};font-weight:600;font-size:0.8rem">'
                     f'{_esc(c["position"])}{(" · " + _esc(c["team"])) if c.get("team") else ""}</span></span> '
                     f'<span class="mono" style="color:var(--tx-mut);font-size:0.72rem">{_esc(c["key"])}</span></a>')
    return '<div class="section-title">Multiple matches — pick one</div>' + "".join(items)


def _nav_buttons(active):
    items = [("/ownership/", "🔍 Player Search"), ("/ownership/browse/", "🌾 FA Browse"),
             ("/ownership/wishlist/", "🪄 Wishlist"), ("/ownership/reverse/", "🔄 Reverse: by team/owner")]
    parts = [f'<a href="{h}" class="btn btn-secondary">{l}</a>' for h, l in items if h != active]
    return '<div style="margin-bottom:14px;display:flex;gap:10px;flex-wrap:wrap">' + "".join(parts) + '</div>'


def _no_data():
    return page_shell("Ownership", '<div class="alert alert-err">No roster snapshots are loaded. '
                      'Run <span class="mono">python -m fdb weekly</span>.</div>', active="/ownership/")


# ------------------------------------------------------------------- routes --
@bp.route("/ownership/")
def ownership_page():
    q = (request.args.get("q") or "").strip()
    pos = (request.args.get("pos") or "").strip().upper()
    team = (request.args.get("team") or "").strip().upper()
    conn = _db()
    try:
        seasons, season = _season_arg(conn)
        if season is None:
            return _no_data()
        form = _search_form(q, season, seasons, pos, team)
        title = ('<div class="page-title">Player Ownership</div>'
                 '<div class="page-sub">Cross-league ownership & free-agent finder</div>')
        nav = _nav_buttons("/ownership/")
        if not q:
            intro = ('<div class="alert">Search any player to see who owns them — or where they\'re still a free '
                     'agent — across every league and pool. Pools are MFL\'s own: conferences (TINO NFL Elite), '
                     'divisions (the NCAA pools, March Madness, TWE, TNT Devy) or the whole league.</div>')
            return page_shell("Ownership", title + nav + form + intro, active="/ownership/")
        cands = _resolve_query(conn, q, pos, team)
        if not cands:
            filt = f' with the active filters ({_esc(pos or "any pos")} / {_esc(team or "any team")})' if pos or team else ""
            return page_shell("Ownership", title + nav + form +
                              f'<div class="alert alert-err">No player matches “{_esc(q)}”{filt}.</div>', active="/ownership/")
        if len(cands) > 1 and not any(c["key"] == q for c in cands):
            return page_shell("Ownership", title + nav + form + _render_candidate_list(cands, season), active="/ownership/")
        chosen = next((c for c in cands if c["key"] == q), cands[0])
        leagues = _ownership_for_player(conn, chosen["key"], season)
        body = nav + form + _render_results(chosen["name"], chosen["position"], season, leagues, key=chosen["key"],
                                            wished=_is_wished(conn, chosen["key"]), is_devy=chosen["is_devy"])
        return page_shell(f"{chosen['name']} — Ownership", body + _WAND_CSS + _WAND_JS, active="/ownership/")
    finally:
        conn.close()


@bp.route("/ownership/reverse/")
def ownership_reverse_page():
    q = (request.args.get("q") or "").strip()
    conn = _db()
    try:
        seasons, season = _season_arg(conn)
        if season is None:
            return _no_data()
        form = ('<form method="get" action="/ownership/reverse/" style="display:flex;gap:10px;align-items:center;'
                'margin-bottom:24px;flex-wrap:wrap">'
                f'<input name="q" value="{_esc(q)}" placeholder="Team or manager name…" autofocus '
                'style="flex:1;min-width:240px;padding:10px 14px;background:var(--bg);border:1px solid var(--edge);'
                'border-radius:6px;color:var(--tx);font-size:0.9rem">'
                f'<select name="season" style="{_SEL}">{_options(seasons, season)}</select>'
                '<button class="btn btn-primary" type="submit">SEARCH</button></form>')
        head = ('<div class="page-title">Team Holdings</div>'
                '<div class="page-sub">Reverse ownership — search by team or owner</div>' + _nav_buttons("/ownership/reverse/"))
        if not q:
            return page_shell("Team Holdings", head + form + '<div class="alert">Search a franchise or manager name '
                              'to see everything they own across every league.</div>', active="/ownership/")
        cands = _resolve_team_query(conn, q, season)
        if not cands:
            return page_shell("Team Holdings", head + form +
                              f'<div class="alert alert-err">No team matches “{_esc(q)}” for {season}.</div>', active="/ownership/")
        if len(cands) > 1 and not any(c["team_name"] == q for c in cands):
            items = "".join(f'<a class="card" href="/ownership/reverse/?{urlencode({"q": c["team_name"], "season": season})}" '
                            f'style="margin-bottom:8px"><span class="card-title" style="margin:0">{_esc(c["team_name"])}</span> '
                            f'<span style="color:var(--tx-mut);font-weight:600;font-size:0.8rem">{c["n_leagues"]} '
                            f'league{"s" if c["n_leagues"] != 1 else ""}</span></a>' for c in cands)
            return page_shell("Team Holdings", head + form + '<div class="section-title">Multiple matches — pick one</div>'
                              + items, active="/ownership/")
        chosen = next((c for c in cands if c["team_name"] == q), cands[0])
        return page_shell(f"{chosen['team_name']} — Holdings", head + form + _render_holdings(
            chosen["team_name"], season, _holdings_for_team(conn, chosen["team_name"], season)), active="/ownership/")
    finally:
        conn.close()


def _browse_params(conn):
    seasons, season = _season_arg(conn)
    return {"seasons": seasons, "season": season, "leagues": _leagues(conn, season) if season else [],
            "league_sel": (request.args.get("league") or "").strip(),
            "conf_sel": (request.args.get("conf") or "").strip(),
            "pos": (request.args.get("pos") or "").strip().upper(),
            "team": (request.args.get("team") or "").strip().upper(),
            "deep": request.args.get("deep") == "1"}


@bp.route("/ownership/browse/")
def ownership_browse_page():
    conn = _db()
    try:
        p = _browse_params(conn)
        if p["season"] is None:
            return _no_data()
        conf_labels, results_html = [], ""
        if p["league_sel"]:
            players, conf_labels, n_pools = _browse_free_agents(conn, p["league_sel"], p["conf_sel"], p["pos"], p["team"],
                                                                p["season"], include_unrostered=p["deep"])
            lname = next((l["lname"] for l in p["leagues"] if l["lid"] == p["league_sel"]), p["league_sel"])
            qs = {"league": p["league_sel"], "conf": p["conf_sel"], "pos": p["pos"], "team": p["team"], "season": p["season"]}
            if p["deep"]:
                qs["deep"] = "1"
            scope = (f" — {_esc(_pool_label(p['conf_sel']))} pool" if p["conf_sel"]
                     else (f" — across {n_pools} pools" if n_pools > 1 else ""))
            results_html = (f'<div class="section-title">{len(players)} free agent{"s" if len(players) != 1 else ""} '
                            f'in {_esc(lname)}{scope}</div>')
            if not players:
                results_html += f'<div class="alert">No free agents match these filters in {_esc(lname)}.</div>'
            else:
                rows = []
                for pl in players:
                    own = f'<a href="/ownership/?{urlencode({"q": pl["pid"], "season": p["season"]})}" class="mono" style="color:var(--tx-mut);font-size:0.7rem">ownership →</a>'
                    wand = _wand(pl["pid"], pl["wished"], context="browse") if not pl["pid"].startswith(("mfl:", "sleeper:")) else ""
                    rows.append(f'<tr><td style="width:44px">{wand}</td><td style="width:30%">{_esc(pl["name"])}</td>'
                                f'<td style="width:8%;color:var(--info);font-weight:700">{_esc(pl["pos"])}</td>'
                                f'<td style="width:8%;color:var(--tx-mut)">{_esc(pl["team"])}</td>'
                                f'<td style="width:16%;color:var(--tx-mut);font-size:0.78rem">rostered in {pl["n_leagues"]} '
                                f'league{"s" if pl["n_leagues"] != 1 else ""}</td>'
                                f'<td style="width:22%;color:var(--accent);font-weight:700;font-size:0.78rem">{_esc(pl["free_label"])}</td>'
                                f'<td>{own}</td></tr>')
                cap = ('<div class="alert" style="margin-top:10px">Showing the first 300 — narrow with position/team '
                       'filters.</div>') if len(players) >= 300 else ""
                results_html += f'<div class="card" style="cursor:default"><table>{"".join(rows)}</table></div>{cap}'
        else:
            results_html = ('<div class="alert">Pick a league to list its free agents. Multi-pool leagues get a pool '
                            'selector after you pick.</div>')
        lg_opts = '<option value="">— pick league —</option>' + "".join(
            f'<option value="{_esc(l["lid"])}"{" selected" if l["lid"] == p["league_sel"] else ""}>{_esc(l["lname"])}</option>'
            for l in p["leagues"])
        conf_select = ""
        if len(conf_labels) > 1:
            conf_select = (f'<select name="conf" style="{_SEL}"><option value="">All pools</option>' + "".join(
                f'<option value="{_esc(c)}"{" selected" if c == p["conf_sel"] else ""}>{_esc(_pool_label(c))}</option>'
                for c in conf_labels) + '</select>')
        form = ('<form method="get" action="/ownership/browse/" style="display:flex;gap:10px;align-items:center;'
                'margin-bottom:24px;flex-wrap:wrap">'
                f'<select name="league" style="{_SEL};min-width:220px" onchange="this.form.submit()">{lg_opts}</select>'
                f'{conf_select}'
                f'<select name="pos" style="{_SEL}">{_options(_POS_OPTIONS, p["pos"], "Any pos")}</select>'
                f'<select name="team" style="{_SEL}">{_options(_TEAM_OPTIONS, p["team"], "Any team")}</select>'
                f'<select name="season" style="{_SEL}">{_options(p["seasons"], p["season"])}</select>'
                '<label style="display:flex;align-items:center;gap:6px;color:var(--tx-mut);font-size:0.78rem;cursor:pointer">'
                f'<input type="checkbox" name="deep" value="1"{" checked" if p["deep"] else ""}> include unrostered NFL</label>'
                '<button class="btn btn-primary" type="submit">BROWSE</button></form>')
        head = ('<div class="page-title">Free Agent Browse</div><div class="page-sub">Every free agent in a league (or '
                'one pool) — sorted by cross-league popularity. 🪄 wands a player onto the draft wishlist.</div>')
        return page_shell("FA Browse", head + _nav_buttons("/ownership/browse/") + form + results_html
                          + _WAND_CSS + _WAND_JS, active="/ownership/")
    finally:
        conn.close()


@bp.route("/ownership/wishlist/")
def ownership_wishlist_page():
    conn = _db()
    try:
        p = _browse_params(conn)
        if p["season"] is None:
            return _no_data()
        body = _nav_buttons("/ownership/wishlist/") + _render_wishlist(conn, p["season"], p["seasons"], p["leagues"],
                                                                       p["league_sel"], request.args.get("free") == "1")
        return page_shell("Draft Wishlist", body + _WAND_CSS + _WAND_JS + _PRIO_JS, active="/ownership/")
    finally:
        conn.close()


def _render_wishlist(conn, season, seasons, leagues, league_sel="", free_only=False):
    rows = conn.execute("SELECT * FROM mart_wishlist").fetchall()
    lg_prio, lname, my_conf, my_note = {}, "", None, ""
    if league_sel:
        lg_prio = {r["player_key"]: r["priority"] for r in
                   conn.execute("SELECT player_key, priority FROM mart_wishlist_priority WHERE league_key = ?", (league_sel,))}
        lname = next((l["lname"] for l in leagues if l["lid"] == league_sel), league_sel)
        platform, league_id = _split_lid(league_sel)
        mine = conn.execute("""SELECT pool_name FROM mart_roster_ownership WHERE season = ? AND platform = ?
                               AND league_id = ? AND is_mine = 1 LIMIT 1""", (season, platform, league_id)).fetchone()
        if mine:
            my_conf = mine["pool_name"] or ""
        else:
            my_note = ('<div class="alert alert-warn">⚠ Couldn\'t find your franchise in this league\'s latest snapshot '
                       '(config/my_franchises.toml) — showing free status across all pools instead.</div>')
    head = '<div class="page-title">Draft Wishlist 🪄</div>'
    if league_sel and my_conf:
        scope_note = (f'priority is scoped to <b>{_esc(lname)}</b> (global rank untouched) • free status shown for '
                      f'<b>your pool: {_esc(_pool_label(my_conf))}</b> (hover for all pools)')
    elif league_sel:
        scope_note = f'priority is scoped to <b>{_esc(lname)}</b> (global rank untouched)'
    else:
        scope_note = 'priority is the global rank (pick a league to scope it)'
    sub = (f'<div class="page-sub">{len(rows)} player{"s" if len(rows) != 1 else ""} flagged for the multi-league draft '
           f'board • free-agency status is live against the {season} snapshots • {scope_note} • 1 = top target, blank = '
           f'unranked (sorts last) — saves as you type, re-sorts on refresh</div>')
    lg_opts = '<option value="">All leagues (global priority)</option>' + "".join(
        f'<option value="{_esc(l["lid"])}"{" selected" if l["lid"] == league_sel else ""}>{_esc(l["lname"])}</option>'
        for l in leagues)
    form = ('<form method="get" action="/ownership/wishlist/" style="display:flex;gap:10px;align-items:center;'
            'margin-bottom:24px;flex-wrap:wrap">'
            f'<select name="league" style="{_SEL};min-width:240px" onchange="this.form.submit()">{lg_opts}</select>'
            f'<select name="season" style="{_SEL}">{_options(seasons, season)}</select>'
            '<label style="display:flex;align-items:center;gap:6px;color:var(--tx-mut);font-size:0.78rem;cursor:pointer">'
            f'<input type="checkbox" name="free" value="1"{" checked" if free_only else ""} onchange="this.form.submit()">'
            ' free agents only</label><button class="btn btn-primary" type="submit">APPLY</button></form>')
    if not rows:
        return head + sub + form + ('<div class="alert">Empty — wand a free agent from the ownership or FA browse '
                                    'view to start building it.</div>')
    entries = []
    for r in rows:
        pid = r["player_key"]
        ownership = _ownership_for_player(conn, pid, season)
        if league_sel:
            lg = next((l for l in ownership if l["full_id"] == league_sel), None)
            free_pools = [_pool_label(c["label"]) for c in lg["conferences"] if c["free"]] if lg else []
            n = len(lg["conferences"]) if lg else 0
            if lg and my_conf is not None and n > 1:
                mine = next((c for c in lg["conferences"] if c["label"] == my_conf), None)
                tip = f'free in: {", ".join(free_pools)}' if free_pools else "not free in any pool"
                is_free = bool(mine and mine["free"])
                free_col = (f'<span style="color:{"var(--accent);font-weight:700" if is_free else "var(--tx-mut)"}" '
                            f'title="{_esc(tip)}">{"FREE" if is_free else "taken"} in your pool ({_esc(_pool_label(my_conf))})</span>')
            elif free_pools:
                label = "FREE AGENT" if n == 1 else f'FREE: {", ".join(free_pools)}'
                free_col, is_free = f'<span style="color:var(--accent);font-weight:700">{_esc(label)}</span>', True
            else:
                free_col = ('<span style="color:var(--tx-mut)">rostered here</span>' if lg
                            else '<span style="color:var(--tx-mut)">no snapshot for this league</span>')
                is_free = False
            prio = lg_prio.get(pid)
        else:
            total_conf = sum(l["n_conf"] for l in ownership)
            total_free = sum(l["n_free"] for l in ownership)
            free_col = (f'<span style="color:var(--accent);font-weight:700">free in {total_free}/{total_conf} pools</span>'
                        if total_free else '<span style="color:var(--tx-mut)">fully rostered now</span>')
            is_free, prio = total_free > 0, r["priority"]
        if free_only and not is_free:
            continue
        entries.append({"row": r, "pid": pid, "free_col": free_col, "prio": prio})
    entries.sort(key=lambda e: (e["prio"] is None, e["prio"] or 0, e["row"]["created_at"] or "", e["pid"]))
    trs = []
    for e in entries:
        r, pid, prio = e["row"], e["pid"], e["prio"]
        own = f'<a href="/ownership/?{urlencode({"q": pid, "season": season})}" class="mono" style="color:var(--tx-mut);font-size:0.7rem">ownership →</a>'
        prio_input = (f'<input type="number" class="prio-input" data-pid="{_esc(pid)}" data-league="{_esc(league_sel)}" '
                      f'value="{_esc("" if prio is None else prio)}" min="1" max="999" placeholder="—" '
                      'style="width:58px;padding:5px 8px;background:var(--bg);border:1px solid var(--edge);border-radius:6px;'
                      'color:var(--tx);font-size:0.82rem;text-align:center">')
        note_input = (f'<input type="text" class="note-input" data-pid="{_esc(pid)}" value="{_esc(r["note"] or "")}" '
                      'maxlength="500" placeholder="note…" style="width:100%;box-sizing:border-box;padding:5px 8px;'
                      'background:var(--bg);border:1px solid var(--edge);border-radius:6px;color:var(--tx);font-size:0.78rem">')
        trs.append(f'<tr><td style="width:44px">{_wand(pid, True, context="wishlist", remove_row=True)}</td>'
                   f'<td style="width:74px">{prio_input}</td><td style="width:20%">{_esc(r["name"] or pid)}</td>'
                   f'<td style="width:6%;color:{theme.pos_var(r["position"])};font-weight:700">{_esc(r["position"] or "")}</td>'
                   f'<td style="width:6%;color:var(--tx-mut)">{_esc(r["team"] or "")}</td><td style="width:22%">{note_input}</td>'
                   f'<td style="width:18%;font-size:0.78rem">{e["free_col"]}</td>'
                   f'<td style="width:10%;color:var(--tx-mut);font-size:0.72rem">added {_esc((r["created_at"] or "")[:10])}</td>'
                   f'<td>{own}</td></tr>')
    if not trs:
        scope_txt = f'your pool ({_pool_label(my_conf)}) of {lname}' if my_conf else (lname or "any league")
        return head + sub + form + my_note + f'<div class="alert">No wishlist player is currently a free agent in {_esc(scope_txt)}.</div>'
    return head + sub + form + my_note + f'<div class="card" style="cursor:default"><table>{"".join(trs)}</table></div>'


# --------------------------------------------------------------------- APIs --
@bp.route("/api/ownership/suggest")
def ownership_suggest_api():
    conn = _db()
    try:
        q = (request.args.get("q") or "").strip()
        return jsonify({"ok": True, "query": q, "suggestions": _resolve_query(
            conn, q, request.args.get("pos"), request.args.get("team"), limit=15)})
    finally:
        conn.close()


@bp.route("/api/ownership/search")
def ownership_api():
    q = (request.args.get("q") or "").strip()
    conn = _db()
    try:
        _, season = _season_arg(conn)
        cands = _resolve_query(conn, q, request.args.get("pos"), request.args.get("team"))
        if not cands or (len(cands) > 1 and not any(c["key"] == q for c in cands)):
            return jsonify({"ok": True, "query": q, "season": season, "candidates": cands})
        chosen = next((c for c in cands if c["key"] == q), cands[0])
        return jsonify({"ok": True, "query": q, "season": season, "player": chosen,
                        "leagues": _ownership_for_player(conn, chosen["key"], season)})
    finally:
        conn.close()


@bp.route("/api/ownership/reverse")
def ownership_reverse_api():
    q = (request.args.get("q") or "").strip()
    conn = _db()
    try:
        _, season = _season_arg(conn)
        cands = _resolve_team_query(conn, q, season)
        if not cands or (len(cands) > 1 and not any(c["team_name"] == q for c in cands)):
            return jsonify({"ok": True, "query": q, "season": season, "candidates": cands})
        chosen = next((c for c in cands if c["team_name"] == q), cands[0])
        return jsonify({"ok": True, "query": q, "season": season, "team": chosen,
                        "leagues": _holdings_for_team(conn, chosen["team_name"], season)})
    finally:
        conn.close()


@bp.route("/api/ownership/browse")
def ownership_browse_api():
    conn = _db()
    try:
        p = _browse_params(conn)
        if not p["league_sel"]:
            return jsonify({"ok": False, "error": "league param required", "leagues": p["leagues"]}), 400
        players, conf_labels, n_pools = _browse_free_agents(conn, p["league_sel"], p["conf_sel"], p["pos"], p["team"],
                                                            p["season"], include_unrostered=p["deep"])
        return jsonify({"ok": True, "season": p["season"], "league": p["league_sel"], "conf": p["conf_sel"],
                        "n_pools": n_pools, "conf_labels": conf_labels, "count": len(players), "players": players})
    finally:
        conn.close()


@bp.route("/api/wishlist")
def wishlist_api():
    league = (request.args.get("league") or "").strip()
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT w.*, lp.priority AS league_priority FROM mart_wishlist w
               LEFT JOIN mart_wishlist_priority lp ON lp.player_key = w.player_key AND lp.league_key = ?
               ORDER BY CASE WHEN ? != '' THEN (lp.priority IS NULL) ELSE (w.priority IS NULL) END,
                        CASE WHEN ? != '' THEN lp.priority ELSE w.priority END,
                        (w.priority IS NULL), w.priority, w.created_at DESC, w.player_key""",
            (league, league, league)).fetchall()
        out = [dict(r) for r in rows]
        if not league:
            for r in out:
                r.pop("league_priority", None)
        return jsonify({"ok": True, "count": len(out), "league": league or None, "wishlist": out})
    finally:
        conn.close()


# Writes: app_* only (the user-entered state; REBUILD_DESIGN §4).
@bp.route("/api/wishlist/toggle", methods=["POST"])
def wishlist_toggle_api():
    data = request.get_json(silent=True) or {}
    pid = (data.get("player_id") or "").strip()
    ctx = (data.get("context") or "").strip()[:80]
    if not pid:
        return jsonify({"ok": False, "error": "player_id required"}), 400
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM mart_player_search WHERE player_key = ? AND gsis_id IS NOT NULL", (pid,)).fetchone():
            return jsonify({"ok": False, "error": f"{pid} is not a gsis_id; the wishlist is keyed on NFL identity "
                                                  "(devy players arrive with the CFB phase)"}), 404
        if conn.execute("SELECT 1 FROM app_wishlist WHERE gsis_id = ?", (pid,)).fetchone():
            conn.execute("DELETE FROM app_wishlist WHERE gsis_id = ?", (pid,))  # priorities cascade
            wished = False
        else:
            conn.execute("INSERT INTO app_wishlist (gsis_id, source_context) VALUES (?, ?)", (pid, ctx))
            wished = True
        conn.commit()
        return jsonify({"ok": True, "player_id": pid, "wished": wished})
    finally:
        conn.close()


@bp.route("/api/wishlist/priority", methods=["POST"])
def wishlist_priority_api():
    """Set/clear a wishlist player's priority (1 = top, null = unranked). With league_id
    ('mfl:30590') the rank is scoped to that league; clearing deletes the row."""
    data = request.get_json(silent=True) or {}
    pid = (data.get("player_id") or "").strip()
    league = (data.get("league_id") or "").strip()
    prio = data.get("priority", None)
    if not pid:
        return jsonify({"ok": False, "error": "player_id required"}), 400
    if prio is not None and (not isinstance(prio, int) or isinstance(prio, bool) or not 1 <= prio <= 999):
        return jsonify({"ok": False, "error": "priority must be an int 1-999 or null"}), 400
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM app_wishlist WHERE gsis_id = ?", (pid,)).fetchone():
            return jsonify({"ok": False, "error": f"{pid} is not on the wishlist"}), 404
        if league:
            platform, league_id = _split_lid(league)
            if not conn.execute("SELECT 1 FROM mart_roster_ownership WHERE platform = ? AND league_id = ? LIMIT 1",
                                (platform, league_id)).fetchone():
                return jsonify({"ok": False, "error": f"unknown league {league}"}), 404
            if prio is None:
                conn.execute("DELETE FROM app_wishlist_priority WHERE gsis_id = ? AND league_key = ?", (pid, league))
            else:
                conn.execute("""INSERT INTO app_wishlist_priority (gsis_id, league_key, priority) VALUES (?,?,?)
                                ON CONFLICT(gsis_id, league_key) DO UPDATE SET priority = excluded.priority,
                                updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now')""", (pid, league, prio))
        else:
            conn.execute("UPDATE app_wishlist SET priority = ? WHERE gsis_id = ?", (prio, pid))
        conn.commit()
        return jsonify({"ok": True, "player_id": pid, "league_id": league or None, "priority": prio})
    finally:
        conn.close()


@bp.route("/api/wishlist/note", methods=["POST"])
def wishlist_note_api():
    data = request.get_json(silent=True) or {}
    pid = (data.get("player_id") or "").strip()
    note = data.get("note", None)
    if not pid:
        return jsonify({"ok": False, "error": "player_id required"}), 400
    if note is not None and not isinstance(note, str):
        return jsonify({"ok": False, "error": "note must be a string or null"}), 400
    note = (note or "").strip()[:500] or None
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM app_wishlist WHERE gsis_id = ?", (pid,)).fetchone():
            return jsonify({"ok": False, "error": f"{pid} is not on the wishlist"}), 404
        conn.execute("UPDATE app_wishlist SET note = ? WHERE gsis_id = ?", (note, pid))
        conn.commit()
        return jsonify({"ok": True, "player_id": pid, "note": note})
    finally:
        conn.close()
