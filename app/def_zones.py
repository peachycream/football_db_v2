"""/defense/ : defense target-zone map. Reads mart_def_* views only (schema 058) and writes nothing.

The computation lives in fdb/def_zones.py (cached per query and database file time); this module is the route and
the page. One defense at a time, with a position filter and a weeks window; the heat metric and overlays switch in
the browser without another request.
"""
import json
import sqlite3
import threading

from flask import Blueprint, Response, abort, request

from fdb import config, def_zones

from .shell import page_shell

bp = Blueprint("def_zones", __name__)
PATH = "/defense/"
_cache, _lock = {}, threading.Lock()


def _db():
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _mtime():
    try:
        return config.DB_PATH.stat().st_mtime
    except OSError:
        return 0


def payload(team, pos, last_n, week=None):
    key = (team, pos, last_n, week, _mtime())
    with _lock:
        if key in _cache:
            return _cache[key]
    conn = _db()
    try:
        data = def_zones.build(conn, team, pos, last_n, week)
    finally:
        conn.close()
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = data
    return data


@bp.route("/api/defense/data")
def api_data():
    team = (request.args.get("team") or "").upper()
    pos = (request.args.get("pos") or "ALL").upper()
    last_n = request.args.get("last", type=int)
    if pos not in def_zones.POSITIONS:
        abort(400)
    week = request.args.get("week", type=int)
    if last_n is not None and not 1 <= last_n <= 30:
        abort(400)
    if week is not None and not 1 <= week <= 30:
        abort(400)
    try:
        data = payload(team, pos, last_n, week)
    except Exception as e:      # a missing view (migration 058 not applied) must say so, not 500 blank
        return Response(json.dumps({"error": f"{type(e).__name__}: {e}"}), status=500, mimetype="application/json")
    if data.get("error"):
        return Response(json.dumps(data), status=404, mimetype="application/json")
    return Response(json.dumps(data), mimetype="application/json")


@bp.route(PATH)
def page():
    conn = _db()
    try:
        teams = [r[0] for r in conn.execute(
            "SELECT DISTINCT defteam FROM mart_def_dropback_week WHERE season = "
            "(SELECT MAX(season) FROM mart_def_target_play) ORDER BY 1")]
        err = ""
    except sqlite3.Error as e:
        teams, err = [], f"{type(e).__name__}: {e} (migration 058 not applied?)"
    finally:
        conn.close()
    boot = json.dumps({"teams": teams, "default": request.args.get("team") or (teams[0] if teams else None), "error": err})
    return page_shell("Defense Map", PAGE.replace("__BOOT__", boot), active=PATH)


PAGE = r"""
<style>
.dz h1{font-size:1.25rem;font-weight:800;letter-spacing:.5px}
.dz .sub{color:var(--tx-mut);font-size:.82rem;margin:.25rem 0 1rem;line-height:1.45}
.dz .bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
.dz select{background:var(--surf-3);color:var(--tx);border:1px solid var(--edge);border-radius:8px;padding:7px 10px;font:inherit;font-size:.85rem}
.dz .chip{background:var(--surf-3);color:var(--tx-mut);border:1px solid var(--edge);border-radius:999px;padding:5px 12px;font-size:.78rem;cursor:pointer;user-select:none}
.dz .chip.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:700}
.dz .lbl{color:var(--tx-dim);font-size:.68rem;text-transform:uppercase;letter-spacing:.7px;margin-right:2px}
.dz .card{background:var(--surf-1);border:1px solid var(--edge);border-radius:14px;padding:16px;margin-bottom:16px}
.dz .head{display:flex;flex-wrap:wrap;align-items:center;gap:24px 36px}
.dz .tm{font-size:2.1rem;font-weight:800;letter-spacing:1px;line-height:1}
.dz .tm small{display:block;font-size:.8rem;color:var(--tx-mut);font-weight:600;letter-spacing:.5px;margin-top:6px}
.dz .stat{border-left:1px solid var(--edge);padding-left:24px;text-align:center}
.dz .stat span{display:block;color:var(--tx-mut);font-size:.7rem;text-transform:uppercase;letter-spacing:.8px}
.dz .stat b{display:block;font-size:2rem;font-weight:800;line-height:1.15}
.dz .stat i{font-style:normal;color:var(--tx-dim);font-size:.74rem}
.dz .stage{position:relative}
.dz canvas{width:100%;height:auto;display:block;border-radius:10px;background:var(--surf-2)}
.dz .tip{position:absolute;pointer-events:none;background:rgba(10,14,26,.94);color:#e8ecf4;border:1px solid var(--edge);border-radius:8px;padding:7px 10px;font-size:.76rem;line-height:1.45;white-space:nowrap;display:none;z-index:5}
.dz .legend{display:flex;align-items:center;gap:8px;font-size:.72rem;color:var(--tx-mut);margin-left:auto}
.dz .legend .g{width:150px;height:9px;border-radius:5px;background:linear-gradient(90deg,#e5483a,#f08a3a,#f2c94c,#a6d65a,#4fc86a)}
.dz .strips{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}
.dz .sp{border-left:1px solid var(--edge);padding:2px 14px;text-align:center}
.dz .sp:first-child{border-left:0}
.dz .sp h4{font-size:.8rem;letter-spacing:.4px;text-transform:uppercase;margin-bottom:2px}
.dz .sp .v{font-size:1.8rem;font-weight:800;margin:4px 0 8px}
.dz .sp .tr{position:relative;height:6px;background:var(--surf-3);border-radius:4px;margin:10px 6px 22px}
.dz .sp .tr .tk{position:absolute;top:-5px;width:3px;height:16px;background:#6b8cff;border-radius:2px}
.dz .sp .tr .tk em{position:absolute;top:17px;left:-18px;width:40px;font-style:normal;font-size:.62rem;color:#6b8cff;text-align:center}
.dz .sp .tr .dt{position:absolute;top:-4px;width:14px;height:14px;border-radius:50%;margin-left:-7px;border:2px solid var(--surf-1)}
.dz .pill{display:inline-block;border:1px solid var(--edge);border-radius:999px;padding:3px 12px;font-size:.74rem;background:var(--surf-2)}
.dz .note{color:var(--tx-mut);font-size:.75rem;line-height:1.5}
.dz table.dt{width:100%;border-collapse:collapse;font-size:.82rem}
.dz .dt th{text-align:right;padding:7px 8px;font-size:.66rem;text-transform:uppercase;letter-spacing:.6px;color:var(--tx-mut);background:var(--surf-2);white-space:nowrap}
.dz .dt th:first-child,.dz .dt td:first-child{text-align:left}
.dz .dt td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--edge-soft);white-space:nowrap}
.dz .dt tr.pl{cursor:pointer}.dz .dt tr.pl:hover td{background:var(--surf-2)}.dz .dt tr.sel td{background:rgb(var(--accent-rgb)/.14)}
.dz .dt .ps{display:inline-block;min-width:34px;text-align:center;border-radius:6px;padding:1px 6px;font-size:.68rem;font-weight:800;background:var(--surf-3);color:var(--tx-mut);margin-left:8px}
.dz .err{color:var(--bad);font-weight:700}
</style>
<div class="dz">
  <h1>DEFENSE MAP</h1>
  <p class="sub">Where a defense's targets, completions and air yards go, in three lanes and seven depth bands, colored against the league in the <b>same zone</b>.
    Green = allows more than the league there; red = allows less. 2026 regular season; FTN charting.</p>
  <div class="bar">
    <span class="lbl">Defense</span><select id="team"></select>
    <span class="lbl" style="margin-left:8px">Targets to</span><span id="pos"></span>
    <span class="lbl" style="margin-left:8px">Window</span><select id="win"></select>
  </div>
  <div id="err" class="err"></div>
  <div class="card" id="card" style="display:none">
    <div class="head">
      <div class="tm"><span id="tmn"></span><small id="tms"></small></div>
      <div class="stat"><span>Rec PPR PPG allowed</span><b id="ppg"></b><i id="ppgr"></i></div>
      <div class="stat"><span>Targets faced</span><b id="tg"></b><i id="tgs"></i></div>
      <div class="stat"><span>TDs allowed</span><b id="tds"></b><i id="tdss"></i></div>
    </div>
    <div class="bar" style="margin:16px 0 8px">
      <span class="lbl">Heat</span><span id="met"></span>
      <span class="lbl" style="margin-left:8px">Overlay</span><span id="ov"></span>
      <div class="legend">allows less<div class="g"></div>allows more</div>
    </div>
    <div class="stage"><canvas id="cv" width="1000" height="590"></canvas><div class="tip" id="tip"></div></div>
    <p class="note" style="margin-top:10px" id="foot"></p>
  </div>
  <div class="card" id="defs" style="display:none"><h4 style="font-size:.85rem;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">Who was targeted: defender in coverage</h4>
  <p class="note" style="margin-bottom:10px">FTN's charted defender on the targeted receiver. Click a defender to isolate his targets on the map; click again to clear. Same position and window filters as the map.</p>
  <div style="overflow-x:auto"><table class="dt" id="dtab"></table></div></div>
  <div class="card" id="strips" style="display:none"><div class="strips" id="sp"></div></div>
</div>
<script>
const BOOT = __BOOT__;
const METRICS = [["targets","Targets"],["completions","Completions"],["comp_pct","Completion %"],["air_yards","Air yards"]];
const POS = ["ALL","WR","TE","RB"];
const S = {team: BOOT.default, pos: "ALL", last: "", week: "", metric: "targets", dots: true, routes: false, td: true, names: false, sel: null, data: null};
const $ = id => document.getElementById(id);
const FW = 880, FH = 470, OX = 60, OY = 40, TOPW = 0.8;        // flat heat canvas, then perspective-projected
const Y0 = -8, Y1 = 50;                                         // yards shown: behind LOS to +50
const yFlat = y => FH - (Math.max(Y0, Math.min(Y1, y)) - Y0) / (Y1 - Y0) * FH;
function proj(fx, fy){ const w = FW*(TOPW + (1-TOPW)*fy/FH); return [OX + (FW-w)/2 + fx/FW*w, OY + fy]; }
const BAND_EDGES = [[-8,0],[0,5],[5,10],[10,15],[15,20],[20,30],[30,50]];
const CSS = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function heat(r){ // ratio -> color; 0.5x..2x on a log scale
  const t = Math.max(0, Math.min(1, 0.5 + Math.log(r)/(2*Math.log(2))));
  const stops = [[229,72,58],[240,138,58],[242,201,76],[166,214,90],[79,200,106]];
  const p = t*(stops.length-1), i = Math.min(stops.length-2, Math.floor(p)), f = p-i;
  return stops[i].map((c,k)=>Math.round(c+(stops[i+1][k]-c)*f));
}
function hash(s){ let h = 2166136261; for (let i=0;i<s.length;i++){ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619);} return (h>>>0)/4294967295; }
const laneRange = l => { const k = "LMR".indexOf(l); return [FW*k/3, FW*(k+1)/3]; };
function dotX(d, j){ const [a,b] = laneRange(d.lane); const m = (b-a)*0.1; return a + m + hash(d.id+"|"+d.week+"|"+j)*(b-a-2*m); }

let LAST = null;   // projected dot positions for hover
function draw(){
  const D = S.data; if(!D) return;
  const cv = $("cv"), ctx = cv.getContext("2d");
  ctx.clearRect(0,0,cv.width,cv.height);
  // 1. flat heat
  const off = document.createElement("canvas"); off.width = FW; off.height = FH;
  const o = off.getContext("2d");
  for (const c of D.cells){
    if (!c.n) continue;
    const [x0,x1] = laneRange(c.lane), [ya,yb] = BAND_EDGES[c.band];
    const top = yFlat(yb), bot = yFlat(ya);
    const col = heat(c.ratio[S.metric]), a = Math.min(1, 0.3 + 0.7*c.n/8);
    o.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${a})`;
    const px = (x1-x0)*0.16, py = (bot-top)*0.14;
    o.fillRect(x0+px, top+py, x1-x0-2*px, bot-top-2*py);
  }
  const bl = document.createElement("canvas"); bl.width = FW; bl.height = FH;
  const b = bl.getContext("2d"); b.filter = "blur(26px)"; b.drawImage(off,0,0);
  // 2. perspective: copy each row scaled to the trapezoid width
  ctx.fillStyle = "#0a0e1a";
  for (let y=0; y<FH; y++){
    const [xa, ya] = proj(0,y), [xb] = proj(FW,y);
    ctx.fillRect(xa, ya, xb-xa, 1.2);
  }
  for (let y=0; y<FH; y++){
    const [xa, ya] = proj(0,y), [xb] = proj(FW,y);
    ctx.drawImage(bl, 0, y, FW, 1, xa, ya, xb-xa, 1.2);
  }
  // 3. yard lines, lane dividers, labels
  ctx.lineWidth = 1; ctx.font = "600 15px system-ui,sans-serif";
  for (const yd of [0,10,20,30,40,50]){
    const fy = yFlat(yd), [xa,ya] = proj(0,fy), [xb] = proj(FW,fy);
    ctx.strokeStyle = yd===0 ? "rgba(235,238,250,.9)" : "rgba(180,190,220,.18)"; ctx.lineWidth = yd===0 ? 2.5 : 1;
    ctx.beginPath(); ctx.moveTo(xa,ya); ctx.lineTo(xb,ya); ctx.stroke();
    ctx.fillStyle = "rgba(200,208,230,.85)";
    ctx.textAlign = "right"; ctx.fillText(yd===0 ? "LOS" : "+"+yd, xa-10, ya+5);
    ctx.textAlign = "left";  ctx.fillText(yd===0 ? "LOS" : "+"+yd, xb+10, ya+5);
  }
  ctx.setLineDash([3,5]); ctx.strokeStyle = "rgba(180,190,220,.3)"; ctx.lineWidth = 1;
  for (const k of [1,2]){ const [x1,y1] = proj(FW*k/3,0), [x2,y2] = proj(FW*k/3,FH); ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke(); }
  ctx.setLineDash([]);
  ctx.fillStyle = "rgba(200,208,230,.7)"; ctx.textAlign = "center"; ctx.font = "700 13px system-ui,sans-serif";
  [["LEFT",1/6],["MIDDLE",.5],["RIGHT",5/6]].forEach(([t,f])=>{ const [x] = proj(FW*f, FH); ctx.fillText(t, x, OY+FH+26); });
  // 4. targets: route lines, dots, TD markers
  LAST = [];
  const dots = D.dots.map((d,j)=>({d, x: dotX(d,j), y: yFlat(d.ay)}));
  if (S.routes){
    ctx.lineJoin = "round";
    for (const {d,x,y} of dots){
      const pts = routePath(d, x, d.ay);
      ctx.strokeStyle = d.td ? "rgba(242,201,76,.9)" : d.c ? "rgba(90,210,120,.55)" : "rgba(235,238,250,.4)";
      ctx.lineWidth = d.td ? 2.2 : 1.4; ctx.beginPath();
      pts.forEach(([fx,fy],i)=>{ const [px,py] = proj(Math.max(0,Math.min(FW,fx)),fy); i ? ctx.lineTo(px,py) : ctx.moveTo(px,py); });
      ctx.stroke();
    }
  }
  const on = d => !S.sel || d.did === S.sel;
  for (const {d,x,y} of dots){
    const [px,py] = proj(x,y); LAST.push({d,px,py});
    if (S.dots){
      ctx.globalAlpha = on(d) ? 1 : 0.12;
      ctx.fillStyle = d.c ? "#5ad278" : "#eef0fa"; ctx.strokeStyle = "rgba(10,14,26,.7)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(px,py,on(d) ? (d.c?4.4:3.8) : (d.c?3.6:3),0,7); ctx.fill(); ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }
  if (S.names){   // covering defender's surname + position beside each target (all, or the selected defender's)
    ctx.font = "600 10px system-ui,sans-serif"; ctx.textAlign = "left"; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(10,14,26,.85)";
    for (const {d} of dots){
      if (!d.did || !on(d)) continue;
      const h = LAST.find(q=>q.d===d), t = `${surname(d.dn)} ${d.dp||""}`.trim();
      ctx.fillStyle = "#cfe0ff"; ctx.strokeText(t, h.px+6, h.py+3); ctx.fillText(t, h.px+6, h.py+3);
    }
  }
  if (S.td) for (const {d,x,y} of dots){ if(!d.td) continue;
    const [px,py] = proj(x,y);
    ctx.fillStyle = "#14192b"; ctx.strokeStyle = "#f2c94c"; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.arc(px,py,14,0,7); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#f2c94c"; ctx.font = "800 11px system-ui,sans-serif"; ctx.textAlign="center"; ctx.fillText("TD",px,py+4);
  }
}

// Stylized route paths (flat coords). FTN charts the targeted receiver's route LABEL, not coordinates, so the
// stem/break shape is drawn from the label and ends exactly at the target's lane and air yards.
function routePath(d, ex, ay){
  const X = FW/53.3, ey = yFlat(Math.max(ay, 0.5)), e = [ex, ey];
  const dirIn = d.lane==="L" ? 1 : d.lane==="R" ? -1 : (hash(d.id+d.week)<.5 ? 1 : -1), out = -dirIn;
  const start = (x, y=0) => [x, yFlat(y)];
  const r = (d.route||"").split(" - ")[1] || "";
  const stemTo = (sx, y, brk) => [start(sx), [sx, yFlat(y)], brk||e];
  switch(r){
    case "Go": return [start(ex), [ex+out*0.4*X, yFlat(ay*0.5)], e];
    case "Slant": return [start(ex-dirIn*Math.max(2,ay)*X*0.9), e];
    case "Hitch/Curl": return [start(ex), [ex, yFlat(ay+1.5)], [ex-dirIn*0.8*X, ey]];
    case "Quick Out": return stemTo(ex-out*4*X, ay, e);
    case "Deep Out": return stemTo(ex-out*6*X, ay, e);
    case "In/Dig": return stemTo(ex-dirIn*7*X, ay, e);
    case "Post": return [start(ex-dirIn*9*X), [ex-dirIn*9*X, yFlat(ay*0.65)], e];
    case "Corner": return [start(ex-out*9*X), [ex-out*9*X, yFlat(ay*0.65)], e];
    case "Shallow Cross/Drag": return [start(ex-dirIn*11*X, 0.6), [ex-dirIn*4*X, ey], e];
    case "Screen": return [start(ex-out*5*X, -1), [ex-out*2*X, yFlat(-0.5)], e];
    case "Swing": return [start(ex-dirIn*6*X, -2), [ex-dirIn*2*X, yFlat(-1)], e];
    case "Wheel": return [start(ex+dirIn*5*X, 0), [ex+dirIn*1.5*X, yFlat(2)], e];
    case "Texas/Angle": return [start(ex+dirIn*3*X), [ex+dirIn*3*X, yFlat(ay*0.6)], e];
    default: return [start(ex), e];
  }
}

const surname = n => n ? n.trim().split(/\s+/).slice(1).join(" ") || n : "?";
const f1 = v => v.toFixed(1), pct = v => (v*100).toFixed(1)+"%", f3 = v => v.toFixed(3);
const FMT = {pct1: pct, num1: f1, num3: f3};
const ord = n => n + ([,"st","nd","rd"][(n%100>>3^1)&&n%10]||"th");

function render(){
  const D = S.data; $("card").style.display = $("strips").style.display = $("defs").style.display = "";
  $("tmn").textContent = D.team;
  $("tms").textContent = `${D.games} ${D.games===1?"game":"games"} · ${D.weeks[0]===D.weeks[1] ? "week "+D.weeks[0] : "weeks "+D.weeks[0]+"–"+D.weeks[1]} · ${D.season}`;
  if (S.sel && !D.defenders.some(x=>x.id===S.sel)) S.sel = null;
  defTable(D);
  const p = D.pts;
  $("ppg").textContent = f1(p.value); $("ppgr").textContent = `${ord(p.rank)} most of ${p.of} · lg avg ${f1(p.league)}`;
  $("tg").textContent = D.targets; $("tgs").textContent = `${D.completions} caught · ${(D.completions/Math.max(1,D.targets)*100).toFixed(1)}%`;
  $("tds").textContent = D.td_allowed; $("tdss").textContent = "receiving";
  $("foot").textContent = `Colors: this defense's per-game ${METRICS.find(m=>m[0]===S.metric)[1].toLowerCase()} in the zone ÷ league's in the same zone, shrunk toward 1 for small cells (n ÷ (n+6)); blank = no targets. Dots sit at the real lane and air yards, spread sideways inside the lane (FTN gives left / middle / right, not exact width). Route lines are drawn from FTN's route label and end at the target; they are a sketch, not tracking data.`;
  const sp = $("sp"); sp.innerHTML = "";
  for (const s of [p, ...D.strips]){
    if (s.value == null) continue;
    const f = FMT[s.fmt], span = (s.hi - s.lo) || 1, pos = v => Math.max(0, Math.min(100, (v - s.lo)/span*100));
    const col = heat(1 + (s.pct-50)/50 * 0.9 ).join(",");
    const el = document.createElement("div"); el.className = "sp";
    el.innerHTML = `<h4>${s.label}</h4><div class="v">${f(s.value)}</div>
      <div class="tr"><div class="tk" style="left:${pos(s.league)}%"><em>LG AVG</em></div><div class="dt" style="left:${pos(s.value)}%;background:rgb(${col})"></div></div>
      <span class="pill">${ord(s.rank)} most allowed of ${s.of}</span>
      <div class="note" style="margin-top:6px">${s.note||"&nbsp;"}</div>`;
    sp.appendChild(el);
  }
  draw();
}

function defTable(D){
  const rows = D.defenders.map(x=>`<tr class="pl${S.sel===x.id?" sel":""}" data-id="${x.id}"><td><b>${x.name||x.id}</b><span class="ps">${x.pos||""}</span></td>
    <td>${x.t}</td><td>${x.c}</td><td>${(x.c/x.t*100).toFixed(0)}%</td><td>${x.yd}</td><td>${(x.ay/x.t).toFixed(1)}</td><td>${x.td||""}</td></tr>`).join("");
  $("dtab").innerHTML = `<tr><th>Defender</th><th>Targets</th><th>Caught</th><th>Comp %</th><th>Yards</th><th>Avg air yds</th><th>TD</th></tr>${rows}`;
  $("dtab").querySelectorAll("tr.pl").forEach(tr=>tr.onclick=()=>{ S.sel = S.sel===tr.dataset.id ? null : tr.dataset.id; defTable(D); draw(); });
  if (D.no_defender) $("dtab").insertAdjacentHTML("beforeend", `<tr><td colspan="7" style="text-align:left;color:var(--tx-dim)">${D.no_defender} targets with no charted defender are not in this table.</td></tr>`);
}
function winOptions(){
  const w = $("win"), D = S.data; if (!D || w.dataset.n == D.all_weeks.length) return;
  w.innerHTML = ""; w.dataset.n = D.all_weeks.length;
  const add = (v,l)=>{ const o = document.createElement("option"); o.value = v; o.textContent = l; w.appendChild(o); };
  add("","All weeks"); [4,6,8].forEach(n=>add("last"+n,"Last "+n+" weeks")); D.all_weeks.forEach(k=>add("wk"+k,"Week "+k));
  w.value = S.week ? "wk"+S.week : S.last ? "last"+S.last : "";
}
async function load(){
  const q = new URLSearchParams({team: S.team, pos: S.pos}); if (S.last) q.set("last", S.last); if (S.week) q.set("week", S.week);
  const r = await fetch("/api/defense/data?" + q), j = await r.json();
  if (j.error){ $("err").textContent = j.error; return; }
  $("err").textContent = ""; S.data = j; winOptions(); render();
}
function chips(el, items, get, set){
  el.innerHTML = "";
  items.forEach(([k,l])=>{ const c = document.createElement("span"); c.className = "chip"+(get(k)?" on":""); c.textContent = l; c.style.marginRight = "4px";
    c.onclick = ()=>{ set(k); chips(el, items, get, set); }; el.appendChild(c); });
}
function init(){
  if (BOOT.error){ $("err").textContent = BOOT.error; return; }
  const t = $("team"); BOOT.teams.forEach(x=>{ const o = document.createElement("option"); o.value = o.textContent = x; t.appendChild(o); });
  t.value = S.team; t.onchange = ()=>{ S.team = t.value; load(); };
  const w = $("win"); w.innerHTML = '<option value="">All weeks</option>';
  w.onchange = ()=>{ const v = w.value; S.last = v.startsWith("last") ? v.slice(4) : ""; S.week = v.startsWith("wk") ? v.slice(2) : ""; load(); };
  chips($("pos"), POS.map(p=>[p, p==="ALL" ? "All (WR/TE/RB)" : p]), k=>S.pos===k, k=>{ S.pos = k; load(); });
  chips($("met"), METRICS, k=>S.metric===k, k=>{ S.metric = k; draw(); });
  const OVS = [["dots","Targets"],["routes","Route lines"],["td","TDs"],["names","Defender names"]];
  chips($("ov"), OVS, k=>S[k], k=>{ S[k] = !S[k]; chips($("ov"), OVS, kk=>S[kk], kk=>{ S[kk] = !S[kk]; draw(); }); draw(); });
  const cv = $("cv"), tip = $("tip");
  cv.onmousemove = ev => {
    const r = cv.getBoundingClientRect(), k = cv.width / r.width, x = (ev.clientX - r.left)*k, y = (ev.clientY - r.top)*k;
    let best = null, bd = 100; for (const h of (LAST||[])){ const dd = (h.px-x)**2 + (h.py-y)**2; if (dd < bd){ bd = dd; best = h; } }
    if (!best){ tip.style.display = "none"; return; }
    const d = best.d; tip.style.display = "block";
    tip.innerHTML = `<b>${d.name||"Unknown"}</b> (target) · ${d.pos||""} · wk ${d.week}<br>${d.route||"route not charted"}<br>${d.did ? "covered by <b>"+(d.dn||d.did)+"</b> "+(d.dp||"") : "no defender charted"}<br>${d.ay} air yds · ${d.c ? "caught for "+d.yd+(d.td?" · TD":"") : "incomplete"}`;
    tip.style.left = (ev.clientX - r.left + 14) + "px"; tip.style.top = (ev.clientY - r.top + 10) + "px";
  };
  cv.onmouseleave = ()=>{ tip.style.display = "none"; };
  load();
}
init();
</script>
"""
