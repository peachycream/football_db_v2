"""/idp/ : IDP start/sit analysis. Reads mart_idp_* / mart_mfl_* / mart_roster_ownership only and writes nothing.

One page per MFL league (scoring differs, so nothing is pooled across leagues). The computation lives in
fdb/idp_start.py and is cached per (league, as-of week, database file time); this module is the route and the page.
Devy / NCAA leagues are not NFL IDP leagues and are not offered.
"""
import json
import sqlite3
import threading

from flask import Blueprint, Response, abort, request

from fdb import config, idp_start

from .shell import page_shell

bp = Blueprint("idp_start", __name__)
PATH = "/idp/"
LEAGUES = ("30590", "55757", "57653", "60398", "60856")   # NFL IDP leagues offered; 46276 excluded at Turon's request (2026-11-22)
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


def league_list(conn):
    names = {r["league_id"]: r["name"] for r in conn.execute("SELECT league_id, name FROM mart_mfl_leagues")}
    return [{"id": lid, "name": names.get(lid, lid)} for lid in LEAGUES if lid in names]


def payload(league, asof):
    key = (league, asof, _mtime())
    with _lock:
        if key in _cache:
            return _cache[key]
    conn = _db()
    try:
        data = idp_start.build_league(conn, league, asof)
        data["leagues"] = league_list(conn)
    finally:
        conn.close()
    with _lock:
        for k in [k for k in _cache if k[0] == league]:
            del _cache[k]
        _cache[key] = data
    return data


@bp.route("/api/idp/data")
def api_data():
    league = request.args.get("league") or LEAGUES[0]
    if league not in LEAGUES:
        abort(404)
    asof = request.args.get("asof", type=int)
    try:
        data = payload(league, asof)
    except Exception as e:                      # a missing view (migration 057 not applied) must say so, not 500 blank
        return Response(json.dumps({"error": f"{type(e).__name__}: {e}"}), status=500, mimetype="application/json")
    return Response(json.dumps(data), mimetype="application/json")


@bp.route(PATH)
def page():
    conn = _db()
    try:
        leagues = league_list(conn)
    except sqlite3.Error:
        leagues = []
    finally:
        conn.close()
    boot = json.dumps({"leagues": leagues, "default": request.args.get("league") or (leagues[0]["id"] if leagues else None)})
    return page_shell("IDP Start/Sit", PAGE.replace("__BOOT__", boot), active=PATH)


PAGE = r"""
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
.ix h1{font-size:1.25rem;font-weight:800;letter-spacing:.5px}
.ix .sub{color:var(--tx-mut);font-size:.82rem;margin:.25rem 0 1rem}
.ix .bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
.ix select,.ix input[type=text]{background:var(--surf-3);color:var(--tx);border:1px solid var(--edge);border-radius:8px;padding:7px 10px;font:inherit;font-size:.85rem}
.ix .chip{background:var(--surf-3);color:var(--tx-mut);border:1px solid var(--edge);border-radius:999px;padding:5px 12px;font-size:.78rem;cursor:pointer;user-select:none}
.ix .chip.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:700}
.ix .tabs{display:flex;gap:4px;border-bottom:1px solid var(--edge);margin:6px 0 16px;flex-wrap:wrap}
.ix .tab{padding:9px 16px;cursor:pointer;color:var(--tx-mut);font-weight:700;font-size:.82rem;letter-spacing:.6px;border-bottom:2px solid transparent}
.ix .tab.on{color:var(--accent);border-color:var(--accent)}
.ix .card{background:var(--surf-1);border:1px solid var(--edge);border-radius:12px;padding:16px;margin-bottom:16px}
.ix .card h3{font-size:.95rem;margin-bottom:4px}
.ix .card .note{color:var(--tx-mut);font-size:.78rem;margin-bottom:12px;line-height:1.45}
.ix .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px}
.ix .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.ix .kpi{background:var(--surf-1);border:1px solid var(--edge);border-radius:12px;padding:12px 14px}
.ix .kpi b{display:block;font-size:1.35rem;margin-top:2px}
.ix .kpi span{color:var(--tx-mut);font-size:.72rem;text-transform:uppercase;letter-spacing:.7px}
.ix table{width:100%;border-collapse:collapse;font-size:.82rem}
.ix th{background:var(--surf-2);text-align:left;padding:8px 8px;font-size:.68rem;text-transform:uppercase;letter-spacing:.6px;color:var(--tx-mut);cursor:pointer;white-space:nowrap}
.ix td{padding:7px 8px;border-bottom:1px solid var(--edge-soft);vertical-align:middle}
.ix tr.pl:hover td{background:var(--surf-2)}
.ix tr.mine td{background:rgb(var(--accent-rgb)/.07)}
.ix .pos{display:inline-block;min-width:30px;text-align:center;border-radius:6px;padding:1px 6px;font-size:.7rem;font-weight:800;color:#0a0e1a}
.ix .nm{font-weight:700;white-space:nowrap}.ix td{white-space:nowrap}.ix .own.taken{display:inline-block;max-width:120px;overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
.ix .tm{color:var(--tx-dim);font-size:.72rem;margin-left:6px}
.ix .up{color:var(--good);font-weight:800}.ix .down{color:var(--bad);font-weight:800}.ix .flat,.ix .new{color:var(--tx-dim)}
.ix .own{font-size:.68rem;font-weight:800;border-radius:5px;padding:2px 6px}
.ix .own.mine{background:var(--accent);color:var(--accent-ink)}
.ix .own.free{background:rgb(var(--good-rgb)/.15);color:var(--good)}
.ix .own.taken{color:var(--tx-dim);font-weight:600}
.ix .flag{font-size:.66rem;border-radius:5px;padding:1px 5px;margin-left:5px;background:rgb(var(--bad-rgb)/.18);color:var(--bad);font-weight:700}
.ix .mix{display:flex;height:9px;border-radius:5px;overflow:hidden;background:var(--surf-3);width:120px}
.ix .mix i{display:block;height:100%}
.ix .rng{position:relative;height:9px;width:130px;background:var(--surf-3);border-radius:5px}
.ix .rng i{position:absolute;top:0;height:100%;background:rgb(var(--info-rgb)/.45);border-radius:5px}
.ix .rng b{position:absolute;top:-3px;width:3px;height:15px;background:var(--tx);border-radius:2px}
.ix .sc{font-weight:800;font-size:.95rem}
.ix .sty{font-size:.68rem;font-weight:700;border-radius:5px;padding:2px 7px}
.ix .sty.Floor{background:rgb(var(--good-rgb)/.16);color:var(--good)}
.ix .sty.Balanced{background:var(--surf-3);color:var(--tx-mut)}
.ix .sty.Big-play{background:rgb(var(--mid-rgb)/.18);color:var(--mid)}
.ix .legend{display:flex;gap:14px;font-size:.74rem;color:var(--tx-mut);flex-wrap:wrap;margin:6px 0 12px}
.ix .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.ix .det td{background:var(--surf-2);padding:14px 18px;white-space:normal}
.ix .det .cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}
.ix .cb{display:grid;grid-template-columns:130px 1fr 52px;gap:8px;align-items:center;font-size:.76rem;margin:3px 0}
.ix .cb div.t{height:10px;background:var(--surf-3);border-radius:5px;overflow:hidden}
.ix .cb div.t i{display:block;height:100%}
.ix .hm td,.ix .hm th{text-align:center;padding:5px 6px;font-size:.74rem;position:static;cursor:default}
.ix .hm th{white-space:normal;max-width:90px}
.ix .big{font-size:.9rem;line-height:1.55}
.ix .big b{color:var(--accent)}
.ix .bt{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.ix .btm{background:var(--surf-2);border-radius:10px;padding:12px}
.ix .btm.win{outline:2px solid var(--accent)}
.ix .btm h4{font-size:.8rem;margin-bottom:6px}
.ix .btm div{display:flex;justify-content:space-between;font-size:.78rem;padding:2px 0;color:var(--tx-mut)}
.ix .btm div b{color:var(--tx)}
.ix .spin{color:var(--tx-mut);padding:40px;text-align:center}
.ix .lu{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.ix .lc{background:var(--surf-2);border:1px solid var(--edge);border-radius:10px;padding:10px 12px;display:flex;justify-content:space-between;align-items:center}
.ix .lc small{color:var(--tx-dim);display:block}
canvas{max-width:100%}
</style>
<div class="ix" id="ix">
  <h1>IDP START / SIT</h1>
  <div class="sub" id="sub">Snap share, how each defender scores under the league's own MFL rules, and what is stable vs boom-or-bust.</div>
  <div class="bar" id="top"></div>
  <div class="tabs" id="tabs">
    <div class="tab on" data-t="board">START / SIT BOARD</div>
    <div class="tab" data-t="lineup">MY LINEUP &amp; TARGETS</div>
    <div class="tab" data-t="anat">POINTS ANATOMY</div>
    <div class="tab" data-t="stab">STABILITY &amp; CORRELATION</div>
    <div class="tab" data-t="meth">METHOD &amp; CHECKS</div>
  </div>
  <div id="view"><div class="spin">Loading…</div></div>
</div>
<script>
(function(){
const BOOT=__BOOT__;
const POSC={DT:'var(--dt)',DE:'var(--dl)',LB:'var(--lb)',CB:'var(--db)',S:'var(--s)'};
const TIERC={stable:'var(--good)',semi:'var(--info)',volatile:'var(--mid)'};
const CATC={tackles:'#00e5a0',assists:'#00a874',tfl:'#7aa2ff',qb_hits:'#5b82e6',pass_breakups:'#9fb9ff',sacks:'#f0b070',forced_fumbles:'#ff8f5a',interceptions:'#ff5470',fumble_recoveries:'#e0a030',scores:'#c084fc'};
const TIERLAB={stable:'Stable',semi:'Semi-stable',volatile:'Volatile (big plays)'};
let D=null,S={tab:'board',pos:'ALL',own:'all',pool:true,sort:'proj',dir:-1,q:'',open:null,league:BOOT.default,asof:null,rpos:'all'};
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const f1=(v,d=1)=>v==null?'–':Number(v).toFixed(d);
const pct=(v,d=0)=>v==null?'–':(v*100).toFixed(d)+'%';
function chip(label,on,fn){const e=document.createElement('span');e.className='chip'+(on?' on':'');e.textContent=label;e.onclick=fn;return e}
function load(){
  $('#view').innerHTML='<div class="spin">Crunching '+esc(S.league)+'… (first load takes a few seconds)</div>';
  const u='/api/idp/data?league='+S.league+(S.asof?'&asof='+S.asof:'');
  fetch(u).then(r=>r.json()).then(d=>{
    if(d.error){$('#view').innerHTML='<div class="alert">'+esc(d.error)+(d.error.includes('no such table')||d.error.includes('mart_idp')?' — apply schema/057 (fdb migrate).':'')+'</div>';return}
    D=d;S.asof=d.asof;top();draw();
  }).catch(e=>{$('#view').innerHTML='<div class="alert">'+esc(e)+'</div>'});
}
function top(){
  const t=$('#top');t.innerHTML='';
  const ls=document.createElement('select');BOOT.leagues.forEach(l=>{const o=document.createElement('option');o.value=l.id;o.textContent=l.name+' ('+l.id+')';if(l.id==S.league)o.selected=true;ls.appendChild(o)});
  ls.onchange=()=>{S.league=ls.value;S.asof=null;load()};t.appendChild(ls);
  const ws=document.createElement('select');for(let w=2;w<=D.through_week+1;w++){const o=document.createElement('option');o.value=w;o.textContent='Start for Wk '+w+(w==D.through_week+1?' (next)':'')+' · data thru Wk '+(w-1);if(w==D.asof)o.selected=true;ws.appendChild(o)}
  ws.onchange=()=>{S.asof=+ws.value;load()};t.appendChild(ws);
  const lr=D.lineup_rules;const sl=Object.entries(lr.slots).map(([p,v])=>p+' '+(v[0]==v[1]?v[0]:v[0]+'–'+v[1])).join(' · ');
  const i=document.createElement('span');i.className='sub';i.style.margin=0;i.textContent='IDP starters '+lr.idp_total+' ('+sl+'; '+lr.flex+' flex)';t.appendChild(i);
}
document.getElementById('tabs').onclick=e=>{const t=e.target.closest('.tab');if(!t)return;S.tab=t.dataset.t;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));if(D)draw()};
function draw(){({board,lineup,anat,stab,meth})[S.tab]()}

/* ---------- shared bits ---------- */
function arrow(r){
  if(r.trend==='new')return '<span class="new" title="needs 5+ games to trend">·</span>';
  const a=r.trend==='up'?'▲':r.trend==='down'?'▼':'–';const d=Math.round(r.snap_delta*100);
  return '<span class="'+r.trend+'" title="last 3 games vs prior 3: '+(d>0?'+':'')+d+' pts of snap share">'+a+' '+(d>0?'+':'')+d+'</span>';
}
function spark(r){
  const W=D.through_week,w=96,h=26,pts=[];
  for(let k=1;k<=W;k++){const v=r.snap_by_week[k];if(v!=null)pts.push([ (k-1)/(Math.max(W-1,1))*(w-6)+3, h-3-v*(h-6),k,v])}
  if(!pts.length)return '';
  const col=r.trend==='up'?'var(--good)':r.trend==='down'?'var(--bad)':'var(--tx-mut)';
  return '<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'"><polyline fill="none" stroke="'+col+'" stroke-width="1.6" points="'+pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')+'"/>'+pts.map(p=>'<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="1.8" fill="'+col+'"><title>Wk '+p[2]+': '+Math.round(p[3]*100)+'%</title></circle>').join('')+'</svg>';
}
function mix(r){
  const t=r.tier_ppg,s=Math.max(0,t.stable)+Math.max(0,t.semi)+Math.max(0,t.volatile);if(s<=0)return '';
  return '<div class="mix" title="Stable '+f1(t.stable)+' · Semi '+f1(t.semi)+' · Volatile '+f1(t.volatile)+' pts/game">'+['stable','semi','volatile'].map(k=>'<i style="width:'+Math.max(0,t[k])/s*100+'%;background:'+TIERC[k]+'"></i>').join('')+'</div>';
}
function ownCell(r){
  const o=r.owner;if(o.status==='mine')return '<span class="own mine">MINE</span>';
  if(o.status==='free')return '<span class="own free">FREE</span>';
  return '<span class="own taken" title="'+esc((o.owners||[]).join(', '))+'">'+esc((o.owners||[''])[0]).slice(0,16)+'</span>';
}
function legend(){return '<div class="legend"><span><i style="background:var(--good)"></i>Stable (tackles, assists)</span><span><i style="background:var(--info)"></i>Semi (TFL, QB hits, PD)</span><span><i style="background:var(--mid)"></i>Volatile (sacks, FF, INT, FR, scores)</span></div>'}

/* ---------- board ---------- */
function rowsF(){
  let r=D.players.filter(p=>p.proj!=null||!S.pool);
  if(S.pool)r=r.filter(p=>p.in_pool);
  if(S.pos!=='ALL')r=r.filter(p=>p.pos===S.pos);
  if(S.own!=='all')r=r.filter(p=>p.owner.status===S.own);
  if(S.q)r=r.filter(p=>p.name.toLowerCase().includes(S.q)||p.team.toLowerCase()===S.q);
  const k=S.sort,g=p=>k==='name'?p.name:k==='snap'?p.snap_avg:k==='delta'?p.snap_delta:k==='ppg'?p.ppg:k==='stable'?p.stable_share:k==='floor'?p.p20:k==='ceil'?p.p80:p.proj;
  return r.sort((a,b)=>{const x=g(a),y=g(b);if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return (x<y?-1:x>y?1:0)*S.dir});
}
function board(){
  const v=$('#view');const lr=D.lineup_rules;
  v.innerHTML='<div class="bar" id="f"></div>'+legend()+'<div class="card" style="padding:0;overflow:auto"><table id="t"></table></div>'+
   '<div class="sub">Start score = expected snaps × per-snap production, each tier shrunk toward the position average by how repeatable it measured (see Method). Range = 20th–80th percentile of the last 8 games. ▲/▼ = last 3 games vs the 3 before, ±5 pts of snap share.</div>';
  const f=$('#f');
  ['ALL','DT','DE','LB','CB','S'].forEach(p=>f.appendChild(chip(p,S.pos===p,()=>{S.pos=p;board()})));
  f.appendChild(document.createTextNode('  '));
  [['all','Everyone'],['mine','My players'],['free','Free agents']].forEach(([k,l])=>f.appendChild(chip(l,S.own===k,()=>{S.own=k;board()})));
  f.appendChild(chip(S.pool?'25%+ snaps, 3+ games':'All with a snap',!S.pool,()=>{S.pool=!S.pool;board()}));
  const q=document.createElement('input');q.type='text';q.placeholder='Search player or team';q.value=S.q;q.oninput=()=>{S.q=q.value.toLowerCase();tbody()};f.appendChild(q);
  head();tbody();
}
function head(){
  const cols=[['#',null],['Player','name'],['Own',null],['Snap % (avg)','snap'],['Trend','delta'],['Snaps by week',null],['Start score','proj'],['Range P20–P80','floor'],['PPG','ppg'],['Points mix','stable'],['Style',null]];
  $('#t').innerHTML='<thead><tr>'+cols.map(c=>'<th data-k="'+(c[1]||'')+'">'+c[0]+(S.sort===c[1]?(S.dir<0?' ↓':' ↑'):'')+'</th>').join('')+'</tr></thead><tbody></tbody>';
  $('#t thead').onclick=e=>{const k=e.target.dataset.k;if(!k)return;if(S.sort===k)S.dir*=-1;else{S.sort=k;S.dir=k==='name'?1:-1}head();tbody()};
}
function tbody(){
  const rows=rowsF();const mx=Math.max(1,...rows.map(r=>r.p80||0));const tb=$('#t tbody');
  tb.innerHTML=rows.slice(0,300).map((r,i)=>{
    const lo=r.p20==null?'':'<div class="rng" title="P20 '+f1(r.p20)+' · P80 '+f1(r.p80)+'"><i style="left:'+r.p20/mx*100+'%;width:'+Math.max(2,(r.p80-r.p20)/mx*100)+'%"></i>'+(r.proj==null?'':'<b style="left:'+Math.min(100,r.proj/mx*100)+'%"></b>')+'</div>';
    return '<tr class="pl '+(r.owner.status==='mine'?'mine':'')+'" data-g="'+r.gsis_id+'"><td>'+(i+1)+'</td><td><span class="pos" style="background:'+POSC[r.pos]+'">'+r.pos+'</span> <span class="nm">'+esc(r.name)+'</span><span class="tm">'+esc(r.team)+'</span>'+(r.bye?'<span class="flag">BYE</span>':'')+(r.missed_last?'<span class="flag">MISSED WK '+(D.asof-1)+'</span>':'')+'</td><td>'+ownCell(r)+'</td><td>'+pct(r.snap_avg)+'</td><td>'+arrow(r)+'</td><td>'+spark(r)+'</td><td class="sc">'+f1(r.proj)+'</td><td>'+lo+'</td><td>'+f1(r.ppg)+'</td><td>'+mix(r)+'</td><td>'+(r.style?'<span class="sty '+r.style+'">'+r.style+'</span>':'')+'</td></tr>'+(S.open===r.gsis_id?detail(r):'');
  }).join('')||'<tr><td colspan="11" class="spin">Nobody matches.</td></tr>';
  tb.onclick=e=>{const tr=e.target.closest('tr.pl');if(!tr)return;S.open=S.open===tr.dataset.g?null:tr.dataset.g;tbody()};
}
function detail(r){
  const mx=Math.max(...D.cats.map(c=>Math.abs(r.cat_ppg[c.key])),1);
  const bars=D.cats.map(c=>'<div class="cb"><span>'+c.label+'</span><div class="t"><i style="width:'+Math.max(0,r.cat_ppg[c.key])/mx*100+'%;background:'+CATC[c.key]+'"></i></div><b>'+f1(r.cat_ppg[c.key])+'</b></div>').join('');
  const wk=[];for(let k=1;k<=D.through_week;k++){const v=r.snap_by_week[k];wk.push('<span style="display:inline-block;width:38px;text-align:center;font-size:.72rem;color:'+(v==null?'var(--tx-dim)':'var(--tx)')+'">'+(v==null?'—':Math.round(v*100))+'<br><small style="color:var(--tx-dim)">W'+k+'</small></span>')}
  const pt=r.proj_tier||{};
  return '<tr class="det"><td colspan="11"><div class="cols"><div><b>Points per game by category</b> <small style="color:var(--tx-mut)">(league '+esc(D.league)+' rules)</small>'+bars+'</div><div><b>Defensive snap share by week (%)</b><div style="margin:8px 0">'+wk.join('')+'</div>'+
  '<div class="big" style="margin-top:10px">Expected <b>'+f1(r.exp_snap_pct==null?null:r.exp_snap_pct*100,0)+'%</b> of snaps (≈'+f1(r.exp_snaps,0)+') → start score <b>'+f1(r.proj)+'</b> = stable '+f1(pt.stable)+' + semi '+f1(pt.semi)+' + volatile '+f1(pt.volatile)+'.<br>Season: '+r.games+' games, <b>'+f1(r.ppg)+'</b> PPG, last 3 games '+f1(r.last3_ppg)+' PPG. Stable share '+pct(r.stable_share)+'.'+(r.owner.status==='taken'?'<br>Owned by '+esc(r.owner.owners.join(', ')):'')+'</div></div></div></td></tr>';
}

/* ---------- lineup ---------- */
function lineup(){
  const v=$('#v')||$('#view');
  const lu=D.my_lineup,ft=D.free_targets;
  const card=p=>'<div class="lc"><div><span class="pos" style="background:'+POSC[p.pos]+'">'+p.pos+'</span> <b>'+esc(p.name)+'</b><small>'+esc(p.team)+' · '+(p.style||'')+'</small></div><div style="text-align:right"><div class="sc">'+f1(p.proj)+'</div>'+arrow({trend:p.trend,snap_delta:D.players.find(x=>x.gsis_id===p.gsis_id).snap_delta})+'</div></div>';
  const tot=lu.reduce((s,p)=>s+p.proj,0);
  v.innerHTML='<div class="kpis"><div class="kpi"><span>Recommended lineup</span><b>'+f1(tot)+' pts</b></div><div class="kpi"><span>Slots filled</span><b>'+lu.length+' / '+D.lineup_rules.idp_total+'</b></div><div class="kpi"><span>For</span><b>Week '+D.asof+'</b></div></div>'+
   '<div class="card"><h3>Start these from your roster</h3><div class="note">Best start scores from players on your franchise (byes excluded): each position\'s minimum first, then the best remaining players fill the flex slots.</div><div class="lu">'+(lu.map(p=>'<div>'+'<small style="color:var(--tx-dim)">'+p.slot+'</small>'+card(p)+'</div>').join('')||'<div class="spin">No rostered IDPs found in the latest snapshot.</div>')+'</div></div>'+
   '<div class="card"><h3>Best free agents in your pool</h3><div class="note">Not owned (or owned fewer times than this pool allows). Compare with the weakest starter above.</div><div class="lu">'+ft.slice(0,18).map(card).join('')+'</div></div>';
}

/* ---------- anatomy ---------- */
function anat(){
  const C=D.categories,v=$('#view');
  v.innerHTML=legend()+'<div class="grid2"><div class="card"><h3>Where each position\'s points come from</h3><div class="note">Share of total points by category, qualifying player-seasons (2025+2026, 6+ games, 25%+ snaps), scored with this league\'s MFL rules.</div><canvas id="c1" height="260"></canvas></div>'+
  '<div class="card"><h3>Stable vs boom-or-bust share</h3><div class="note">Tier share of points by position, and how spread out a player\'s weekly points are (coefficient of variation: lower = steadier week to week).</div><canvas id="c2" height="260"></canvas><div id="cv" style="margin-top:10px"></div></div></div><div class="card big" id="ins"></div>';
  const P=Object.keys(C.share);
  new Chart($('#c1'),{type:'bar',data:{labels:P,datasets:D.cats.map(c=>({label:c.label,data:P.map(p=>(C.share[p][c.key]||0)*100),backgroundColor:CATC[c.key]}))},options:chartOpt(true,'% of points')});
  new Chart($('#c2'),{type:'bar',data:{labels:P,datasets:['stable','semi','volatile'].map(t=>({label:TIERLAB[t],data:P.map(p=>(C.tier_share[p][t]||0)*100),backgroundColor:t==='stable'?'#00e5a0':t==='semi'?'#7aa2ff':'#f0b070'}))},options:chartOpt(true,'% of points')});
  $('#cv').innerHTML='<table class="hm"><tr><th></th>'+P.map(p=>'<th>'+p+'</th>').join('')+'</tr>'+['stable','semi','volatile','total'].map(t=>'<tr><th style="text-align:left">'+(t==='total'?'All points':TIERLAB[t])+' · CV</th>'+P.map(p=>'<td>'+f1(C.cv[p][t],2)+'</td>').join('')+'</tr>').join('')+'</table>';
  const hi=P.map(p=>[p,C.tier_share[p].stable]).sort((a,b)=>b[1]-a[1]);
  $('#ins').innerHTML='<b>Read-out.</b> Tackles and assists supply the most points at <b>'+hi[0][0]+'</b> ('+pct(hi[0][1])+') and the least at <b>'+hi[hi.length-1][0]+'</b> ('+pct(hi[hi.length-1][1])+'); the big-play tier is worth '+pct(C.tier_share[hi[hi.length-1][0]].volatile)+' there. Everything here is MFL points under <b>'+esc(D.league)+'</b>\'s rules, so a league that pays more for sacks makes the volatile slice larger.';
}
function chartOpt(stack,yl){
  const tc=getComputedStyle(document.body).color;
  return {responsive:true,indexAxis:'y',plugins:{legend:{position:'bottom',labels:{color:tc,boxWidth:10,font:{size:10}}},tooltip:{callbacks:{label:c=>c.dataset.label+': '+c.parsed.x.toFixed(1)+'%'}}},scales:{x:{stacked:stack,max:100,ticks:{color:tc},grid:{color:'rgba(128,140,180,.12)'},title:{display:true,text:yl,color:tc}},y:{stacked:stack,ticks:{color:tc},grid:{display:false}}}};
}

/* ---------- stability ---------- */
function heatc(v,mx){if(v==null)return 'transparent';const a=Math.min(Math.abs(v)/mx,1);return v>=0?'rgba(0,229,160,'+(a*.75).toFixed(2)+')':'rgba(255,84,112,'+(a*.75).toFixed(2)+')'}
function stab(){
  const R=D.reliability,C=D.categories,v=$('#view');
  const src=S.rpos==='all'?R.all:R.by_pos[S.rpos];
  const keys=[...D.cats.map(c=>c.key),'tier:stable','tier:semi','tier:volatile'];
  v.innerHTML=legend()+'<div class="card"><h3>How repeatable is each category? (split-half reliability)</h3><div class="note">Each player-season is split into odd and even games; the correlation between halves of per-snap points (position-demeaned), stepped up to the full sample (Spearman-Brown). Higher = a player\'s past rate predicts his future rate; near zero = mostly luck. Games per player-season ≈ '+f1(R.games_mean,0)+'. Tier colour = the tier declared before measuring.</div><div class="bar" id="rp"></div><div style="position:relative;height:320px"><canvas id="c3"></canvas></div></div>'+
  '<div class="grid2"><div class="card"><h3>What drives who scores more</h3><div class="note">Correlation of each category\'s points per game with total points per game, across players at a position. High = that category is what separates the top scorers.</div><div id="ct"></div></div>'+
  '<div class="card"><h3>Snap share vs points</h3><div class="note">Every qualifying 2026 player: average defensive snap share against points per game.</div><canvas id="c4" height="230"></canvas><div id="sc" class="legend"></div></div></div>'+
  '<div class="card"><h3>Do the same players do everything? (category × category)</h3><div class="note">Correlation of per-snap rates across players, position-demeaned. Green = players strong in one tend to be strong in the other; red = they trade off.</div><div id="mx" style="overflow:auto"></div></div>';
  const rp=$('#rp');['all',...Object.keys(C.share)].forEach(p=>rp.appendChild(chip(p==='all'?'All positions':p,S.rpos===p,()=>{S.rpos=p;stab()})));
  const lab=k=>k.startsWith('tier:')?'TIER · '+TIERLAB[k.slice(5)]:D.cats.find(c=>c.key===k).label;
  const tierOf=k=>k.startsWith('tier:')?k.slice(5):D.cats.find(c=>c.key===k).tier;
  const hex={stable:'#00e5a0',semi:'#7aa2ff',volatile:'#f0b070'};
  new Chart($('#c3'),{type:'bar',data:{labels:keys.map(lab),datasets:[{data:keys.map(k=>src[k]&&src[k].r_full!=null?src[k].r_full:null),backgroundColor:keys.map(k=>hex[tierOf(k)]),borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>'reliability '+(c.parsed.y==null?'n/a':c.parsed.y.toFixed(2))+' (n='+(src[keys[c.dataIndex]]||{}).n+')'}}},scales:{y:{suggestedMin:-.1,suggestedMax:.8,ticks:{color:getComputedStyle(document.body).color},grid:{color:'rgba(128,140,180,.12)'}},x:{ticks:{color:getComputedStyle(document.body).color,maxRotation:45,font:{size:10}},grid:{display:false}}}}});
  const P=Object.keys(C.corr_total);
  $('#ct').innerHTML='<table class="hm"><tr><th></th>'+P.map(p=>'<th>'+p+'</th>').join('')+'</tr>'+keys.map(k=>'<tr><th style="text-align:left">'+lab(k)+'</th>'+P.map(p=>{const x=C.corr_total[p][k];return '<td style="background:'+heatc(x,1)+'">'+(x==null?'–':x.toFixed(2))+'</td>'}).join('')+'</tr>').join('')+'</table>';
  const pl=D.players.filter(p=>p.in_pool&&p.ppg!=null&&p.snap_avg!=null);
  new Chart($('#c4'),{type:'scatter',data:{datasets:Object.keys(POSC).map(p=>({label:p,data:pl.filter(x=>x.pos===p).map(x=>({x:x.snap_avg*100,y:x.ppg,n:x.name})),backgroundColor:{DT:'#ff8fa3',DE:'#ff5470',LB:'#7aa2ff',CB:'#a78bfa',S:'#c4b5fd'}[p],pointRadius:3}))},options:{responsive:true,plugins:{legend:{labels:{color:getComputedStyle(document.body).color,boxWidth:8}},tooltip:{callbacks:{label:c=>c.raw.n+': '+c.raw.x.toFixed(0)+'% snaps, '+c.raw.y.toFixed(1)+' PPG'}}},scales:{x:{title:{display:true,text:'avg defensive snap share (%)',color:getComputedStyle(document.body).color},ticks:{color:getComputedStyle(document.body).color},grid:{color:'rgba(128,140,180,.12)'}},y:{title:{display:true,text:'MFL points per game',color:getComputedStyle(document.body).color},ticks:{color:getComputedStyle(document.body).color},grid:{color:'rgba(128,140,180,.12)'}}}}});
  $('#sc').innerHTML=Object.entries(C.snap_corr).map(([p,o])=>'<span><b>'+p+'</b> season r = '+f1(o.season,2)+' · single game r = '+f1(o.game,2)+'</span>').join('');
  const m=C.matrix,L=m.keys.map(k=>D.cats.find(c=>c.key===k).label);
  $('#mx').innerHTML='<table class="hm"><tr><th></th>'+L.map(l=>'<th>'+l+'</th>').join('')+'</tr>'+m.keys.map((k,i)=>'<tr><th style="text-align:left">'+L[i]+'</th>'+m.values[i].map((x,j)=>'<td style="background:'+(i===j?'var(--surf-3)':heatc(x,.6))+'">'+(i===j?'':x==null?'–':x.toFixed(2))+'</td>').join('')+'</tr>').join('')+'</table>';
}

/* ---------- method ---------- */
function meth(){
  const r=D.reconcile,b=D.backtest,i=D.info,w=D.weights,v=$('#view');
  const bm=b?Object.entries(b.methods):[];const best=bm.length?bm.reduce((a,c)=>c[1].spearman_within_pos_week>a[1].spearman_within_pos_week?c:a)[0]:null;
  const nm={start_score:'Start score',season_ppg:'Season-to-date PPG',last3_ppg:'Last-3-games PPG'};
  v.innerHTML='<div class="kpis"><div class="kpi"><span>Rows matching MFL exactly</span><b>'+pct(r.exact,1)+'</b></div><div class="kpi"><span>Within 1 point</span><b>'+pct(r.within_1,1)+'</b></div><div class="kpi"><span>Season totals rank corr.</span><b>'+f1(r.season_spearman,3)+'</b></div><div class="kpi"><span>Player-games checked</span><b>'+(r.n||0).toLocaleString()+'</b></div></div>'+
  '<div class="card"><h3>1 · Do our points equal MFL\'s?</h3><div class="note big">Each defender-game is scored with <b>'+esc(D.league)+'</b>\'s MFL rules (every rule naming the player\'s MFL position applies, additively) and compared with MFL\'s own reported score for that player-week. Exact match by position: '+Object.entries(r.by_pos||{}).map(([p,x])=>p+' '+pct(x)).join(' · ')+'. The gap is the stat provider: MFL credits an occasional tackle, assist or TFL that nflverse does not (and blocked kicks / special-teams scores are not in our counts).'+(i.unscored_cols.length?' <b>Not scored by this league:</b> '+i.unscored_cols.join(', ')+'.':'')+' Stats come from nflverse (92% exact in the common league) rather than PFF (28%); fumble recoveries and return TDs come from PFF because nflverse lacks them.</div></div>'+
  (b?'<div class="card"><h3>2 · Does the start score beat the obvious alternatives? (walk-forward, 2026 weeks '+b.weeks[0]+'–'+b.weeks[1]+')</h3><div class="note">For every week the score uses only earlier games, and its reliability constants come from 2025 alone. Compared with the points players actually scored that week ('+b.n.toLocaleString()+' player-games; players who did not play are not scored because nobody knew beforehand).</div><div class="bt">'+bm.map(([k,m])=>'<div class="btm '+(k===best?'win':'')+'"><h4>'+nm[k]+(k===best?' · best':'')+'</h4><div>Rank corr. within position-week<b>'+f1(m.spearman_within_pos_week,3)+'</b></div><div>Rank corr. pooled<b>'+f1(m.spearman_pooled,3)+'</b></div><div>Top-quartile hit rate<b>'+pct(m.top_quartile_hit)+'</b></div><div>Mean abs. error (pts)<b>'+f1(m.mae)+'</b></div><div>Bias (pts)<b>'+f1(m.bias,2)+'</b></div></div>').join('')+'</div></div>':'<div class="card"><div class="note">Walk-forward check is shown for the next-week view only.</div></div>')+
  '<div class="card"><h3>3 · How the pieces are defined</h3><div class="note big"><b>Snap share</b> = player defensive snaps ÷ team defensive snaps (PFR). <b>Trend</b> compares the mean of the last 3 games with the 3 before (needs 5+ games): ▲ ≥ +'+w.trend_points*100+' pts, ▼ ≤ −'+w.trend_points*100+' pts. <b>Expected snaps</b> = recency-weighted share (weights '+w.recency.join(', ')+', newest first) × the team\'s recent defensive snaps per game. <b>Tiers</b> were declared before measuring: stable = solo + assisted tackles; semi = TFL, QB hits, passes defended; volatile = sacks, forced fumbles, INT, fumble recoveries, return TDs/safeties. <b>Per-snap production</b> by tier = SUM(points) ÷ SUM(snaps), shrunk toward the position mean with weight games ÷ (games + k); k = '+Object.entries(w.shrink_k).map(([t,x])=>t+' '+f1(x,1)).join(', ')+' (from measured reliability: the less repeatable a tier, the more it is pulled to the average). <b>Pool</b>: avg snap share ≥ '+w.min_avg_snap*100+'% and ≥ '+w.min_games+' games. <b>Style</b>: Floor = top quartile of stable share in the pool, Big-play = bottom quartile.</div></div>'+
  '<div class="card"><h3>4 · Caveats</h3><div class="note big">• Scoring uses the league\'s '+i.rule_season+' rules for every season (MFL keeps only the current rule set). • Position = MFL\'s listing for this league, so a hybrid is scored as MFL lists him. • Reliabilities are modest everywhere (see Stability): the start score is a better ordering than PPG, not a prediction of any single game. • '+(i.ambiguous_gsis?i.ambiguous_gsis+' players map to two MFL ids and are left out. • ':'')+((i.snap_players-i.mapped_players)>0?(i.snap_players-i.mapped_players)+' players with defensive snaps are not IDP-listed in this league (position outside DT/DE/LB/CB/S or unmapped). ':'')+'• Injury status, matchup strength and weather are not in the score.</div></div>';
}

if(!BOOT.leagues.length){$('#view').innerHTML='<div class="alert">No IDP leagues found (apply schema/057 and run the loaders).</div>'}else load();
})();
</script>
"""
