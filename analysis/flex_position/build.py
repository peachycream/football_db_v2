"""Flex-position analysis: which position should fill the flex slots in each MFL league.

Read-only. Opens database/fdb.db mode=ro and creates the views of schema/056 as TEMP views, so nothing is written
to the DB until the migration is applied. Writes flex_position.html (one standalone file, Chart.js from cdnjs).

Usage:  python build.py
"""
import json
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(ROOT, "database", "fdb.db")
SQL = os.path.join(ROOT, "schema", "056_mart_mfl_flex.sql")
OUT = os.path.join(HERE, "flex_position.html")

OFF = ["QB", "RB", "WR", "TE"]
IDP = ["DT", "DE", "LB", "CB", "S"]


def connect():
    con = sqlite3.connect("file:" + DB.replace("\\", "/") + "?mode=ro", uri=True)
    sql = re.sub(r"CREATE VIEW", "CREATE TEMP VIEW", open(SQL, encoding="utf-8").read())
    for stmt in sql.split(";\n"):
        stmt = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
        if stmt:
            con.execute(stmt)
    return con


def build():
    con = connect()
    leagues = []
    for lid, season, name, nfr, unit, rpp, pool, total, idp, off in con.execute(
            "SELECT league_id, season, name, teams, pool_unit, rosters_per_player, pool_teams, total_starters, idp_starters, off_starters "
            "FROM mart_mfl_lineup_size ORDER BY name"):
        slots = {p: (mn, mx) for p, mn, mx in con.execute(
            "SELECT position, min_slots, max_slots FROM mart_mfl_position_slots WHERE league_id=?", (lid,))}
        groups = {}
        for gname, plist, gtotal in (("Offense", OFF, off), ("IDP", IDP, idp)):
            mins = sum(slots[p][0] for p in plist if p in slots)
            flex = gtotal - mins
            elig = [p for p in plist if p in slots and slots[p][1] > slots[p][0]]
            groups[gname] = {"total": gtotal, "min_sum": mins, "flex": flex, "eligible": elig}
            assert flex >= 0, (lid, gname, gtotal, mins)
        players = {}
        thru = 0
        for pos, games, pts, wk in con.execute(
                "SELECT position, games, points, through_week FROM mart_mfl_player_games "
                "WHERE league_id=? AND games > 0 AND position IN ('QB','RB','WR','TE','DT','DE','LB','CB','S')", (lid,)):
            players.setdefault(pos, []).append([int(games), round(pts / games, 3)])  # PPG at read time
            thru = max(thru, wk)
        for p in players:
            players[p].sort(key=lambda r: -r[1])
        teams = pool / rpp  # teams competing for one supply of players
        leagues.append({"id": lid, "season": season, "name": name, "teams": teams, "franchises": nfr, "pool_unit": unit,
                        "pool_teams": pool, "rpp": rpp, "through_week": thru,
                        "slots": {p: list(v) for p, v in slots.items()}, "groups": groups, "players": players})
    return leagues


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flex Position Analysis</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#fff;--fg:#1c1f26;--mut:#667085;--card:#f6f7f9;--line:#e1e4ea;
--QB:#7a4fd6;--RB:#2f7de1;--WR:#e8892b;--TE:#1f9d8b;--DT:#a8506b;--DE:#c9402e;--LB:#4e8f3a;--CB:#b79b1d;--S:#5c6b7a}
@media(prefers-color-scheme:dark){:root{--bg:#14161b;--fg:#e8eaee;--mut:#98a1b3;--card:#1d2027;--line:#2c3039;
--QB:#a784ee;--RB:#5aa0f2;--WR:#f2a455;--TE:#43c4b1;--DT:#d77b95;--DE:#ea6e5c;--LB:#7bbf64;--CB:#d9bd45;--S:#93a2b3}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:0 0 8px}.sub{color:var(--mut);margin-bottom:14px}
.bar{display:flex;flex-wrap:wrap;gap:14px;align-items:end;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:14px}
.bar label{display:flex;flex-direction:column;font-size:12px;color:var(--mut);gap:4px}
select,input[type=range]{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:14px}
.verdict{font-size:15px}.verdict b{font-size:18px}.chip{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:4px 8px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}.note{color:var(--mut);font-size:12px;margin-top:6px}
.cv{position:relative;height:290px}.cv.tall{height:360px}
</style></head><body><main>
<h1>Which position should fill the flex spots?</h1>
<div class="sub" id="sub"></div>
<div class="bar">
 <label>League<select id="lg"></select></label>
 <label>Lineup side<select id="gr"><option>Offense</option><option>IDP</option></select></label>
 <label>Minimum games played: <b id="mgv"></b><input id="mg" type="range" min="1" max="10" value="3"></label>
 <label>Flex-pool depth: <b id="dpv"></b><input id="dp" type="range" min="1" max="4" step="0.5" value="1"></label>
</div>
<div class="card verdict" id="verdict"></div>
<div class="grid">
 <div class="card"><h2>Average PPG of the flex band, by position</h2><div class="cv"><canvas id="c1"></canvas></div>
  <div class="note" id="n1"></div></div>
 <div class="card"><h2>Who actually fills the flex pool</h2><div class="cv"><canvas id="c2"></canvas></div>
  <div class="note" id="n2"></div></div>
</div>
<div class="card"><h2>PPG by position rank (thick = the flex band; dashed line = last fixed starter)</h2>
 <div class="cv tall"><canvas id="c3"></canvas></div><div class="note" id="n3"></div></div>
<div class="grid">
 <div class="card"><h2>Starting requirements</h2><div id="req"></div></div>
 <div class="card"><h2>Best flex position, every league</h2><div id="all"></div></div>
</div>
<div class="card note">
<b>Method.</b> Starters come from each league's MFL <code>league</code> endpoint (<code>starters</code>); scoring is MFL's own reported
points per player-week (<code>playerScores</code>) for that league, regular season to date. MFL gives a min-max range per position and a total
per side, so <i>fixed slots = the minimum at each position</i> and <i>flex slots = side total &minus; sum of minimums</i>; only positions whose
max exceeds their min can take flex. The fixed line at a position is teams &times; its minimum. The <i>flex band</i> is the next
<i>depth</i> = teams &times; flex slots &times; the depth slider players past that line (default: exactly the players who end up in flex).
The <i>flex pool</i> is the best remaining eligible players, taking at most (max &minus; min) &times; teams at any one position.
PPG = points / games played (a game = a non-zero score). The pool is every NFL player with the minimum games, owned or not; positions are MFL's
own for that player id. Recomputed live in this page, nothing is averaged across rates.
</div></main>
<script>
const DATA=__DATA__;
const COL=n=>getComputedStyle(document.documentElement).getPropertyValue('--'+n).trim();
const $=id=>document.getElementById(id);
const leagues=DATA, byId={};leagues.forEach(l=>byId[l.id]=l);
leagues.forEach(l=>$('lg').add(new Option(l.name+' ('+l.teams+'-team pool)',l.id)));
let charts={};
function calc(l,gname,mg,dm){
  const g=l.groups[gname];const el=g.eligible;
  const res={g,el,pos:{},pool:[],D:l.teams*g.flex*dm,slotsTotal:l.teams*g.flex};
  el.forEach(p=>{
    const all=(l.players[p]||[]).filter(r=>r[0]>=mg);
    const fixed=l.teams*l.slots[p][0];const cap=(l.slots[p][1]-l.slots[p][0])*l.teams;
    const bw=Math.min(Math.ceil(res.D),cap);
    const band=all.slice(fixed,fixed+bw);
    const avg=band.length?band.reduce((a,r)=>a+r[1],0)/bw:null; // an unfilled slot scores 0
    res.pos[p]={all,fixed,cap,bw,band,avg,short:band.length<bw,lastFixed:all[fixed-1]?all[fixed-1][1]:null};
    all.slice(fixed,fixed+cap).forEach(r=>res.pool.push({p,ppg:r[1]}));
  });
  res.pool.sort((a,b)=>b.ppg-a.ppg);
  res.top=res.pool.slice(0,Math.ceil(res.D));
  res.share={};el.forEach(p=>res.share[p]=0);res.top.forEach(r=>res.share[r.p]++);
  const ranked=el.filter(p=>res.pos[p].avg!=null).sort((a,b)=>res.pos[b].avg-res.pos[a].avg);
  res.best=ranked[0]||null;res.ranked=ranked;
  return res;
}
const chip=(p,t)=>'<span class="chip" style="background:'+COL(p)+'">'+p+'</span>'+(t||'');
const rankHtml=(r)=>r.ranked.slice(0,3).map((p,i)=>(i+1)+'. '+chip(p,' '+f1(r.pos[p].avg)+' PPG, '+r.share[p]+' pool spots')).join(' &nbsp; ');
const f1=x=>x==null?'–':x.toFixed(1);
function render(){
  const l=byId[$('lg').value],gname=$('gr').value,mg=+$('mg').value,dm=+$('dp').value;
  $('mgv').textContent=mg;$('dpv').textContent=dm+'×';
  $('sub').textContent=l.name+' · season '+l.season+' through week '+l.through_week+' · '+l.franchises+' franchises, '+l.pool_unit.toLowerCase()+' pool of '+l.pool_teams+(l.rpp>1?' / '+l.rpp+' owners per player':'')+' = '+l.teams+' teams competing';
  const r=calc(l,gname,mg,dm),g=r.g;
  if(g.flex===0){
    $('verdict').innerHTML='<b>No flex slots on the '+gname+' side.</b> The lineup minimums fill all '+g.total+' starting spots.';
  }else if(!r.best){$('verdict').innerHTML='<b>The league cannot fill its flex slots from real players.</b> No eligible position has any NFL player with '+mg+'+ games left past its fixed starters. Lower the minimum games.';}
  else{
    const b=r.best,sec=r.ranked[1];
    $('verdict').innerHTML='<b>Use <span class="chip" style="background:'+COL(b)+'">'+b+'</span> in flex.</b> '+
     g.flex+' '+gname+' flex slot'+(g.flex>1?'s':'')+' per team ('+g.total+' starters − '+g.min_sum+' fixed), '+r.slotsTotal+' league-wide. '+
     b+' flex band averages <b>'+f1(r.pos[b].avg)+' PPG</b>'+(sec?', ahead of '+sec+' ('+f1(r.pos[sec].avg)+')':'')+
     '; '+b+' holds '+r.share[b]+' of the top '+r.top.length+' flex-pool spots.'+
     (r.pos[b].bw<Math.ceil(r.D)?' <span style="color:var(--mut)">Only '+r.pos[b].bw+' of the '+Math.ceil(r.D)+' flex slots can be '+b+' (max − min limit), so the rest go to '+(sec?sec:'the next position')+'.</span>':'')+
     (r.ranked.length&&Object.keys(r.share).sort((a,c)=>r.share[c]-r.share[a])[0]!==b?
       ' <span style="color:var(--mut)">(Most pool spots: '+Object.keys(r.share).sort((a,c)=>r.share[c]-r.share[a])[0]+' — a deeper position, lower average.)</span>':'');
  }
  if(r.best&&g.flex>0)$('verdict').innerHTML+='<div class="note" style="margin-top:8px;font-size:13px"><b>Ranking:</b> '+rankHtml(r)+'</div>';
  Object.values(charts).forEach(c=>c.destroy());charts={};
  const ps=r.el;const tc=COL('mut');Chart.defaults.color=tc;Chart.defaults.borderColor=COL('line');
  const opts={responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}}};
  charts.a=new Chart($('c1'),{type:'bar',data:{labels:ps,datasets:[{data:ps.map(p=>r.pos[p].avg),backgroundColor:ps.map(COL)}]},
    options:{...opts,scales:{y:{beginAtZero:true,title:{display:true,text:'PPG'}}}}});
  charts.b=new Chart($('c2'),{type:'bar',data:{labels:ps,datasets:[{data:ps.map(p=>r.share[p]),backgroundColor:ps.map(COL)}]},
    options:{...opts,scales:{y:{beginAtZero:true,title:{display:true,text:'players in top '+r.top.length+' of the pool'}}}}});
  const ds=[];const maxN=Math.max(1,...ps.map(p=>r.pos[p].all.length));
  const lines=[];
  ps.forEach(p=>{const q=r.pos[p],lo=q.fixed,hi=q.fixed+q.bw;
    ds.push({label:p,data:q.all.map((x,i)=>({x:i+1,y:x[1]})),borderColor:COL(p),backgroundColor:COL(p),pointRadius:0,tension:.2,
      borderWidth:2,segment:{borderWidth:c=>(c.p0DataIndex>=lo&&c.p0DataIndex<hi)?6:1.5}});
    lines.push({p,x:lo+0.5});});
  const plug={id:'fixedLines',afterDatasetsDraw(ch){const{ctx,chartArea:a,scales:s}=ch;ctx.save();ctx.setLineDash([5,4]);ctx.lineWidth=1;
    lines.forEach(L=>{const x=s.x.getPixelForValue(L.x);if(x<a.left||x>a.right)return;ctx.strokeStyle=COL(L.p);ctx.beginPath();ctx.moveTo(x,a.top);ctx.lineTo(x,a.bottom);ctx.stroke();});ctx.restore();}};
  charts.c=new Chart($('c3'),{type:'line',data:{datasets:ds},plugins:[plug],
    options:{responsive:true,maintainAspectRatio:false,parsing:false,plugins:{legend:{display:true,labels:{usePointStyle:true}}},
      scales:{x:{type:'linear',min:1,max:Math.min(maxN,Math.max(...ps.map(p=>r.pos[p].fixed+r.pos[p].bw))*1.6+5),title:{display:true,text:'rank within position (by PPG)'}},
              y:{beginAtZero:true,title:{display:true,text:'PPG'}}}}});
  const short=ps.filter(p=>r.pos[p].short);
  $('n1').textContent='Band = ranks '+(ps.length?'(teams × minimum)+1':'')+' onward, '+Math.ceil(r.D)+' players deep, capped at (max−min) × teams per position.'+(short.length?' Supply runs out before the band is full at: '+ps.filter(p=>r.pos[p].short).map(p=>p+' ('+r.pos[p].band.length+' of '+r.pos[p].bw+')').join(', ')+'; unfilled slots count as 0 PPG.':'');
  $('n2').textContent='Best '+r.top.length+' remaining eligible players league-wide after the fixed starters; capped at (max−min) × teams per position.';
  $('n3').textContent='Vertical dashes mark each position’s last fixed starter; the thick segment is the flex band. Where a curve is flat through its band, that position holds value deeper.';
  let h='<table><tr><th>Position</th><th>Min</th><th>Max</th><th>Fixed (league)</th><th>Flex-eligible</th></tr>';
  (gname==='Offense'?['QB','RB','WR','TE']:['DT','DE','LB','CB','S']).forEach(p=>{const s=l.slots[p];if(!s)return;
    h+='<tr><td><span class="chip" style="background:'+COL(p)+'">'+p+'</span></td><td>'+s[0]+'</td><td>'+s[1]+'</td><td>'+(s[0]*l.teams)+'</td><td>'+(s[1]>s[0]?'yes':'no')+'</td></tr>';});
  h+='</table><div class="note">'+gname+' starters '+g.total+' = '+g.min_sum+' fixed + '+g.flex+' flex.</div>';$('req').innerHTML=h;
  let a='<table><tr><th>League</th><th>Offense</th><th>IDP</th></tr>';
  leagues.forEach(L=>{a+='<tr><td>'+L.name+'</td>';['Offense','IDP'].forEach(G=>{const x=calc(L,G,mg,dm);
    a+='<td>'+(L.groups[G].flex===0?'<span style="color:var(--mut)">no flex</span>':x.best?x.ranked.slice(0,3).map((p,i)=>(i+1)+'. '+chip(p,' '+f1(x.pos[p].avg)+(x.pos[p].bw<Math.ceil(x.D)?'*':''))).join('<br>'):'–')+'</td>';});a+='</tr>';});
  $('all').innerHTML=a+'</table><div class="note">Uses the current games and depth settings. * = capped by the max − min limit, so it fills only part of the flex block. – = not enough players to fill flex.</div>';
}
['lg','gr','mg','dp'].forEach(i=>$(i).addEventListener('input',render));render();
</script></body></html>
"""


if __name__ == "__main__":
    data = build()
    for l in data:
        print(l["name"], l["teams"], "wk", l["through_week"], {k: (v["flex"], v["eligible"]) for k, v in l["groups"].items()})
    html = HTML.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", OUT, len(html) // 1024, "KB")
