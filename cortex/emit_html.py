"""Self-contained interactive graph view (force-directed, vanilla JS canvas).

`render_page` produces a standalone HTML document for opening in a browser;
`render_body` produces just the styled widget (no <html>/<head>/<body>) for
embedding. Both inline all data and code — no network, no dependencies.
"""

from __future__ import annotations

import json

from .graph import Graph
from .model import DEPENDENCY_KINDS, FILE, MODULE


def _prepare(graph: Graph, limit: int) -> dict:
    """Top-N nodes by rank plus the dependency edges among them."""
    ranked = sorted(graph.nodes.values(), key=lambda n: n.rank, reverse=True)
    keep_nodes = ranked[:limit]
    keep = {n.id for n in keep_nodes}
    nodes = [{
        "id": n.id,
        "label": n.path or n.name,
        "name": n.name,
        "kind": n.kind,
        "rank": n.rank,
        "loc": n.loc,
        "line": n.line,
        "summary": n.summary,
    } for n in keep_nodes]
    links = []
    seen = set()
    for e in graph.edges:
        if e.kind in DEPENDENCY_KINDS and e.src in keep and e.dst in keep and e.src != e.dst:
            k = (e.src, e.dst)
            if k not in seen:
                seen.add(k)
                links.append({"s": e.src, "t": e.dst})
    return {"nodes": nodes, "links": links}


_CSS = """
:root{--bg:#f7f7f8;--panel:#ffffff;--fg:#1a1a1e;--muted:#6b6b76;--edge:#c9c9d1;--border:#e3e3e8;}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--panel:#171a21;--fg:#e8e8ee;--muted:#9a9aa6;--edge:#2c313c;--border:#252a33;}}
:root[data-theme=dark]{--bg:#0f1115;--panel:#171a21;--fg:#e8e8ee;--muted:#9a9aa6;--edge:#2c313c;--border:#252a33;}
:root[data-theme=light]{--bg:#f7f7f8;--panel:#ffffff;--fg:#1a1a1e;--muted:#6b6b76;--edge:#c9c9d1;--border:#e3e3e8;}
*{box-sizing:border-box;}
.cx-wrap{position:relative;width:100%;height:100%;min-height:520px;background:var(--bg);color:var(--fg);
  font:13px/1.4 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;border-radius:10px;overflow:hidden;border:1px solid var(--border);}
.cx-canvas{display:block;width:100%;height:100%;cursor:grab;}
.cx-canvas:active{cursor:grabbing;}
.cx-panel{position:absolute;top:12px;left:12px;background:var(--panel);border:1px solid var(--border);
  border-radius:8px;padding:10px 12px;max-width:260px;box-shadow:0 4px 16px rgba(0,0,0,.12);}
.cx-panel h3{margin:0 0 6px;font-size:13px;}
.cx-panel .cx-sub{color:var(--muted);font-size:11px;margin-bottom:8px;}
.cx-panel .cx-live{color:#2fb36b;font-size:11px;margin-bottom:6px;}
.cx-panel .cx-live:empty{display:none;}
.cx-search{width:100%;padding:5px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--fg);font-size:12px;}
.cx-legend{position:absolute;bottom:12px;left:12px;background:var(--panel);border:1px solid var(--border);
  border-radius:8px;padding:8px 10px;display:flex;flex-wrap:wrap;gap:4px 12px;max-width:70%;}
.cx-legend span{display:inline-flex;align-items:center;gap:5px;color:var(--muted);font-size:11px;}
.cx-dot{width:9px;height:9px;border-radius:50%;display:inline-block;}
.cx-tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--border);
  border-radius:6px;padding:6px 9px;font-size:11px;max-width:320px;box-shadow:0 4px 16px rgba(0,0,0,.18);display:none;z-index:5;}
.cx-tip b{color:var(--fg);} .cx-tip .k{color:var(--muted);}
.cx-hint{position:absolute;bottom:12px;right:12px;color:var(--muted);font-size:11px;}
"""

_JS = r"""
(function(){
  const ROOT = document.getElementById('CX_ID');
  const DATA = CX_DATA;
  const KIND_COLORS = {module:'#4c8dff',file:'#38b48b',class:'#c86bff',function:'#f0a03c',
    method:'#f6c945',heading:'#5ac8e0',concept:'#e06c9f',config_key:'#8a94a6',external:'#7a869a',dir:'#5f6b7a'};
  const canvas = ROOT.querySelector('.cx-canvas');
  const tip = ROOT.querySelector('.cx-tip');
  const search = ROOT.querySelector('.cx-search');
  const ctx = canvas.getContext('2d');
  let W=0,H=0,DPR=Math.min(2,window.devicePixelRatio||1);

  // ---- STATIC layout: solved once, deterministically, then frozen. ---------
  // Seeded PRNG from node ids => same graph always produces the same map.
  function hashStr(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;}
  function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
  // Cluster seed: nodes start near their top-level directory's spot on a ring,
  // so folders settle as visible communities.
  const groupOf = n => n.label.includes('/') ? n.label.split('/')[0] : (n.kind==='external'||n.kind==='concept' ? '_ext' : '_root');
  const groups = new Map();
  DATA.nodes.forEach(n=>{const g=groupOf(n); if(!groups.has(g)) groups.set(g,groups.size);});
  const G = Math.max(1,groups.size);
  const nodes = DATA.nodes.map(n=>{
    const rnd = mulberry32(hashStr(n.id));
    const gi = groups.get(groupOf(n));
    const ang = gi/G*2*Math.PI;
    return {...n, x:Math.cos(ang)*300+(rnd()-0.5)*180, y:Math.sin(ang)*220+(rnd()-0.5)*180, vx:0, vy:0};
  });
  const byId = new Map(nodes.map(n=>[n.id,n]));
  const links = DATA.links.map(l=>({s:byId.get(l.s),t:byId.get(l.t)})).filter(l=>l.s&&l.t);
  const deg = new Map(); nodes.forEach(n=>deg.set(n.id,0));
  links.forEach(l=>{deg.set(l.s.id,deg.get(l.s.id)+1);deg.set(l.t.id,deg.get(l.t.id)+1);});
  const R = n => 3 + Math.sqrt(n.rank||0)*11 + Math.min(6,(deg.get(n.id)||0)*0.5);
  const neigh = new Map(nodes.map(n=>[n.id,new Set()]));
  links.forEach(l=>{neigh.get(l.s.id).add(l.t.id);neigh.get(l.t.id).add(l.s.id);});

  // Solve to equilibrium synchronously (no visible motion, ever).
  (function solve(){
    let alpha=1; const DECAY=0.022, MIN=0.0018, FRIC=0.55, MAX_V=28;
    for(let it=0; it<800 && alpha>MIN; it++){
      alpha += (0-alpha)*DECAY;
      const rep=-260;
      for(let i=0;i<nodes.length;i++){const a=nodes[i];
        for(let j=i+1;j<nodes.length;j++){const b=nodes[j];
          let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy;
          if(d2>176400)continue; d2=Math.max(d2,64);
          const d=Math.sqrt(d2),f=rep/d2*alpha,fx=dx/d*f,fy=dy/d*f;
          a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;}}
      for(const l of links){let dx=l.t.x-l.s.x,dy=l.t.y-l.s.y;
        const d=Math.sqrt(dx*dx+dy*dy)||1,f=(d-80)*0.045*alpha,fx=dx/d*f,fy=dy/d*f;
        l.s.vx+=fx;l.s.vy+=fy;l.t.vx-=fx;l.t.vy-=fy;}
      for(const n of nodes){
        n.vx+=-n.x*0.012*alpha; n.vy+=-n.y*0.012*alpha;
        n.vx*=FRIC; n.vy*=FRIC;
        const s=Math.hypot(n.vx,n.vy); if(s>MAX_V){n.vx*=MAX_V/s;n.vy*=MAX_V/s;}
        n.x+=n.vx; n.y+=n.vy;}
    }
    // Overlap relax: firmly separate any nodes still touching.
    for(let pass=0;pass<200;pass++){let moved=false;
      for(let i=0;i<nodes.length;i++){const a=nodes[i];
        for(let j=i+1;j<nodes.length;j++){const b=nodes[j];
          const min=R(a)+R(b)+4; let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy);
          if(d<min){moved=true; if(d<0.01){dx=1;dy=0;d=1;}
            const push=(min-d)/2/d; a.x-=dx*push;a.y-=dy*push;b.x+=dx*push;b.y+=dy*push;}}}
      if(!moved)break;}
  })();

  // ---- camera + interaction state (layout itself never changes) ------------
  let view={x:0,y:0,k:1}, hover=null, sel=null, panning=false, last=null, query='';
  const toScreen = n => ({x:n.x*view.k+view.x, y:n.y*view.k+view.y});

  // ---- live activity glow (active when the page is served by `cortex serve`)
  // Agents' lookups (query/context/sync) append to .cortex/activity.jsonl;
  // we poll it and glow the touched nodes + the paths between them. The
  // layout never moves — only light. Silently disabled on a plain file/artifact.
  const GLOW_MS=4000, GLOW_COLOR='#ffb340';
  let lastTs=Date.now(), liveOn=false, glowTimer=null, glowRAF=null;
  const liveBadge=ROOT.querySelector('.cx-live');
  function animateGlow(){
    if(glowRAF)return;
    const step=()=>{
      const now=performance.now(); let active=false;
      for(const n of nodes){if(n.glowT&&now-n.glowT<GLOW_MS){active=true;break;}}
      if(!active)for(const l of links){if(l.glowT&&now-l.glowT<GLOW_MS){active=true;break;}}
      draw();
      if(active) glowRAF=requestAnimationFrame(step); else {glowRAF=null;draw();}
    };
    glowRAF=requestAnimationFrame(step);
  }
  function applyEvent(ev){
    const set=new Set(ev.ids), now=performance.now(); let any=false;
    for(const id of ev.ids){const n=byId.get(id); if(n){n.glowT=now; any=true;}}
    for(const l of links){ if(set.has(l.s.id)&&set.has(l.t.id)) l.glowT=now; }
    if(any) animateGlow();
  }
  async function poll(){
    try{
      const r=await fetch('activity?since='+lastTs,{cache:'no-store'});
      if(!r.ok)throw 0;
      const evs=await r.json();
      if(!liveOn){liveOn=true; if(liveBadge)liveBadge.textContent='● live — glows on agent access';}
      for(const ev of evs){lastTs=Math.max(lastTs,ev.t); applyEvent(ev);}
    }catch(e){ if(!liveOn&&glowTimer){clearInterval(glowTimer);glowTimer=null;} }
  }
  if(location.protocol==='http:'||location.protocol==='https:'){
    glowTimer=setInterval(poll,1000); poll();
  }

  function fit(){
    let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
    for(const n of nodes){x0=Math.min(x0,n.x);x1=Math.max(x1,n.x);y0=Math.min(y0,n.y);y1=Math.max(y1,n.y);}
    const bw=Math.max(60,x1-x0), bh=Math.max(60,y1-y0);
    view.k=Math.min(1.6, Math.min((W-90)/bw,(H-90)/bh));
    view.x=W/2-(x0+x1)/2*view.k; view.y=H/2-(y0+y1)/2*view.k;
  }
  function resize(){const r=ROOT.getBoundingClientRect();W=r.width;H=r.height;
    canvas.width=W*DPR;canvas.height=H*DPR;canvas.style.width=W+'px';canvas.style.height=H+'px';
    ctx.setTransform(DPR,0,0,DPR,0,0);fit();draw();}

  const rankCut = (()=>{ // label the top ~24 hubs by default
    const rs=nodes.map(n=>n.rank||0).sort((a,b)=>b-a);
    return rs[Math.min(24,rs.length-1)]||0; })();

  function draw(){
    ctx.clearRect(0,0,W,H);
    const hl = sel ? neigh.get(sel.id) : null;
    const nowMs = performance.now();
    const glowOf = o => o.glowT ? Math.max(0,1-(nowMs-o.glowT)/GLOW_MS) : 0;
    // edges
    for(const l of links){
      const a=toScreen(l.s), b=toScreen(l.t);
      const lit = sel && (l.s===sel||l.t===sel);
      if(sel && !lit){ctx.globalAlpha=0.05;ctx.strokeStyle=getVar('--edge');ctx.lineWidth=1;}
      else if(lit){ctx.globalAlpha=0.95;ctx.strokeStyle='#5b8cff';ctx.lineWidth=1.8;}
      else {ctx.globalAlpha=0.22;ctx.strokeStyle=getVar('--edge');ctx.lineWidth=1;}
      ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
      const eg=glowOf(l);
      if(eg>0){ctx.globalAlpha=eg;ctx.strokeStyle=GLOW_COLOR;ctx.lineWidth=2.6;
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}
      if(lit){ // direction arrowhead near the target
        const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,ux=dx/d,uy=dy/d;
        const tx=b.x-ux*(R(l.t)*Math.sqrt(view.k)+4), ty=b.y-uy*(R(l.t)*Math.sqrt(view.k)+4);
        ctx.beginPath();ctx.moveTo(tx,ty);
        ctx.lineTo(tx-ux*7-uy*3.5,ty-uy*7+ux*3.5);
        ctx.lineTo(tx-ux*7+uy*3.5,ty-uy*7-ux*3.5);
        ctx.closePath();ctx.fillStyle='#5b8cff';ctx.fill();}
    }
    // nodes
    for(const n of nodes){
      const p=toScreen(n), r=Math.max(2,R(n)*Math.sqrt(view.k));
      const inFocus = !sel || n===sel || (hl&&hl.has(n.id));
      const matches = !query || n.label.toLowerCase().includes(query);
      ctx.globalAlpha = (inFocus&&matches)?1:0.08;
      ctx.beginPath();ctx.arc(p.x,p.y,r,0,6.283);
      ctx.fillStyle=KIND_COLORS[n.kind]||'#888';ctx.fill();
      if(n===sel||n===hover){ctx.lineWidth=2;ctx.strokeStyle=getVar('--fg');ctx.stroke();}
      const ng=glowOf(n);
      if(ng>0){ctx.globalAlpha=Math.max(ctx.globalAlpha,ng*0.95);
        ctx.lineWidth=3;ctx.strokeStyle=GLOW_COLOR;
        ctx.beginPath();ctx.arc(p.x,p.y,r+2.5+3.5*ng,0,6.283);ctx.stroke();}
      const label = (inFocus&&matches) && (n===sel||n===hover||(sel&&hl.has(n.id))||(!sel&&(n.rank||0)>=rankCut));
      if(label){
        ctx.font=(n===sel?'bold ':'')+'11px ui-sans-serif,system-ui';
        ctx.lineWidth=3;ctx.strokeStyle=getVar('--bg');
        ctx.strokeText(n.name,p.x+r+3,p.y+3);   // halo for legibility
        ctx.fillStyle=getVar('--fg');ctx.fillText(n.name,p.x+r+3,p.y+3);}
    }
    ctx.globalAlpha=1;
  }
  function getVar(v){return getComputedStyle(ROOT).getPropertyValue(v).trim()||'#888';}
  function pick(mx,my){let best=null,bd=1e9;
    for(const n of nodes){const p=toScreen(n),r=Math.max(5,R(n)*Math.sqrt(view.k));
      const d=(p.x-mx)**2+(p.y-my)**2; if(d<r*r&&d<bd){bd=d;best=n;}}return best;}

  canvas.addEventListener('mousemove',e=>{const rect=canvas.getBoundingClientRect();
    const mx=e.clientX-rect.left,my=e.clientY-rect.top;
    if(panning&&last){view.x+=mx-last.x;view.y+=my-last.y;last={x:mx,y:my};draw();return;}
    const h=pick(mx,my);
    if(h!==hover){hover=h;draw();}
    if(hover){tip.style.display='block';tip.style.left=Math.min(W-320,mx+14)+'px';tip.style.top=(my+14)+'px';
      tip.innerHTML='<b>'+esc(hover.label)+'</b><br><span class=k>'+hover.kind+(hover.line?' · line '+hover.line:'')
        +' · rank '+hover.rank+(hover.loc?' · '+hover.loc+' LOC':'')+'</span>'+(hover.summary?'<br>'+esc(hover.summary):'');
      canvas.style.cursor='pointer';}
    else{tip.style.display='none';canvas.style.cursor='grab';}});
  canvas.addEventListener('mousedown',e=>{const rect=canvas.getBoundingClientRect();
    const mx=e.clientX-rect.left,my=e.clientY-rect.top;
    panning=true; last={x:mx,y:my};});
  canvas.addEventListener('click',e=>{const rect=canvas.getBoundingClientRect();
    const n=pick(e.clientX-rect.left,e.clientY-rect.top);
    sel = (n===sel)? null : n;      // click node = light up; click again/empty = clear
    draw();});
  window.addEventListener('mouseup',()=>{panning=false;last=null;});
  canvas.addEventListener('wheel',e=>{e.preventDefault();const rect=canvas.getBoundingClientRect();
    const mx=e.clientX-rect.left,my=e.clientY-rect.top;const f=Math.exp(-e.deltaY*0.001);
    const nk=Math.max(0.15,Math.min(5,view.k*f));
    view.x=mx-(mx-view.x)*(nk/view.k);view.y=my-(my-view.y)*(nk/view.k);view.k=nk;draw();},{passive:false});
  search.addEventListener('input',()=>{query=search.value.toLowerCase();draw();});
  function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
  window.addEventListener('resize',resize);
  resize();
})();
"""


def render_body(graph: Graph, limit: int = 250, title: str = "Cortex graph") -> str:
    data = _prepare(graph, limit)
    dom_id = "cortex-graph"
    kinds = sorted({n["kind"] for n in data["nodes"]})
    legend = "".join(
        f'<span><i class="cx-dot" style="background:{_color(k)}"></i>{k}</span>' for k in kinds)
    js = (_JS.replace("CX_ID", dom_id)
             .replace("CX_DATA", _safe_json(data)))
    return f"""<style>{_CSS}</style>
<div class="cx-wrap" id="{dom_id}" style="height:78vh">
  <canvas class="cx-canvas"></canvas>
  <div class="cx-panel">
    <h3>{_esc(title)}</h3>
    <div class="cx-sub">{len(data['nodes'])} nodes · {len(data['links'])} edges · size = importance</div>
    <div class="cx-live"></div>
    <input class="cx-search" placeholder="filter by name/path…">
  </div>
  <div class="cx-legend">{legend}</div>
  <div class="cx-tip"></div>
  <div class="cx-hint">static map · scroll = zoom · drag = pan · click a node = light up its connections</div>
</div>
<script>{js}</script>"""


# CSP for the standalone/served page (the published artifact uses render_body,
# which the claude.ai platform wraps in its own CSP). 'unsafe-inline' is required
# because the page inlines its own script/style, but connect-src 'self' means an
# injected script still could not exfiltrate to any external host, and no remote
# code/resource of any kind can load.
_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'")


def render_page(graph: Graph, limit: int = 250, title: str = "Cortex graph") -> str:
    body = render_body(graph, limit, title)
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta http-equiv='Content-Security-Policy' content=\"{_CSP}\">"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(title)}</title>"
            f"<style>html,body{{margin:0;height:100%;background:#0f1115}}</style></head>"
            f"<body>{body}</body></html>")


def _safe_json(obj) -> str:
    """JSON for embedding inside a <script> element. Escapes the characters that
    could otherwise break out of the element or terminate the script early, so
    scanned content (docstrings, names) can never inject markup or code."""
    s = json.dumps(obj, ensure_ascii=False)
    return (s.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
             .replace(" ", "\\u2028").replace(" ", "\\u2029"))


def _color(kind: str) -> str:
    return {"module": "#4c8dff", "file": "#38b48b", "class": "#c86bff",
            "function": "#f0a03c", "method": "#f6c945", "heading": "#5ac8e0",
            "concept": "#e06c9f", "config_key": "#8a94a6", "external": "#7a869a",
            "dir": "#5f6b7a"}.get(kind, "#888")


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
