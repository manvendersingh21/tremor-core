/* Dashboard rooms: live feed, per-model ledger, benchmarks, evals. Moved from the old HUD page. */
(()=>{
const $=id=>document.getElementById(id);
const dashes=document.querySelectorAll('.dash');
function h(tag,txt,cls){const e=document.createElement(tag);if(txt!=null)e.textContent=txt;if(cls)e.className=cls;return e}
const f=(v,d=0)=>v==null?'–':Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const median=a=>{if(!a.length)return null;const s=[...a].sort((x,y)=>x-y),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2};

// tiers: themed label (Gothic and Hollowkeep) and the real name, always shown together
const ORDER=['cache','phone_3b','mac_3b','gpu_small','gpu_large','crusoe'];
const T={
  cache:{th:'The Crypt',real:'Supabase cache',c:'--cache',model:'exact, then cosine ≥ 0.97'},
  phone_3b:{th:'The Familiar',real:'Phone 3B',c:'--phone',model:'Gemma 3 (no calls yet)'},
  mac_3b:{th:'The Lantern',real:'Mac 3B (experiment, off)',c:'--mac',model:'Qwen2.5-3B (no calls yet)'},
  gpu_small:{th:'The Manor',real:'GPU 30B (self-hosted)',c:'--gpus',model:'qwen3:30b-instruct (no calls yet)'},
  gpu_large:{th:'The Castle',real:'H200 120B (optional)',c:'--gpul',model:'gpt-oss-120b (no calls yet)'},
  crusoe:{th:"The Count's Tower",real:'Crusoe (cloud)',c:'--crusoe',model:'no calls yet'}};
function lab(k){const s=h('span');s.append(h('span',T[k].th,'th'),h('span',T[k].real,'rl'));return s}
function dotted(k,...kids){const s=h('span');const d=h('span',null,'dot');d.style.background=`var(${T[k].c})`;s.append(d,...kids);return s}

// themes: set on every .dash block; the choice is saved in localStorage
const THEMES={gothic:'Gothic',hollowkeep:'Hollowkeep',standard:'Standard',vicecity:'Vice City'};
function setTheme(t,save){
  dashes.forEach(d=>d.dataset.theme=t);
  document.querySelectorAll('[data-theme-btn]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.themeBtn===t));
  if(save)try{localStorage.setItem('chimera-theme',t)}catch(_){}
}
document.querySelectorAll('[data-theme-btn]').forEach(b=>b.onclick=()=>setTheme(b.dataset.themeBtn,true));
let t0='gothic';try{t0=new URLSearchParams(location.search).get('theme')||localStorage.getItem('chimera-theme')||t0}catch(_){}
if(t0==='halloween')t0='hollowkeep';
setTheme(THEMES[t0]?t0:'gothic',false);
document.querySelectorAll('.how').forEach(b=>b.append(lab(b.dataset.k)));

// ---- live state ----
const S={tok:0,usd:0,calls:0,asum:0,acount:0,low:0,total:0,top:0,cache:{calls:0,avoided:0},hi:{},rows:new Map(),allLat:[]};
ORDER.forEach(k=>S.hi[k]=0);
const D={tok:0,usd:0,kept:0};
// Old events have no per_tier: rebuild it from local_tokens / gpu_tokens / cloud_tokens (output only, input unknown).
function perTier(e){
  if(e.per_tier&&Object.keys(e.per_tier).length)return e.per_tier;
  const p={},ms=e.latency_ms||0;
  if(e.local_tokens>0||e.tier_used==='local')p.mac_3b={model:'local 3B (not logged)',input_tokens:0,output_tokens:e.local_tokens||0,latency_ms:e.tier_used==='local'?ms:0,dollars:0};
  if(e.gpu_tokens>0||e.tier_used==='gpu')p.gpu_small={model:'GPU (not logged)',input_tokens:0,output_tokens:e.gpu_tokens||0,latency_ms:ms,dollars:0};
  if(e.cloud_tokens>0||/^(cloud|top)/.test(e.tier_used))p.crusoe={model:'cloud (not logged)',input_tokens:0,output_tokens:e.cloud_tokens||0,latency_ms:ms,dollars:0};
  return p;
}
const isCache=e=>/cache/.test(e.tier_used);
const tokens=u=>(u.input_tokens||0)+(u.output_tokens||0);

function addEvent(e){
  if(!e._meta&&!S.srcSet){S.srcSet=1;const s=$('src');if(/waiting/.test(s.textContent))s.textContent='live: this machine\'s telemetry log'}
  if(e._meta){S.srcSet=1;const s=$('src');s.textContent=e._meta.source;const demo=/demo/.test(e._meta.source);s.className='badge'+(demo?' demo':'');$('ledsrc').hidden=!demo;return}
  const cache=isCache(e),pt=cache?{}:perTier(e);
  S.calls++;S.tok+=e.tokens_saved||0;S.usd+=e.dollars_saved||0;S.allLat.push(e.latency_ms||0);if(S.allLat.length>1000)S.allLat.shift();
  if(e.acceptance_rate_alpha!=null){S.asum+=e.acceptance_rate_alpha;S.acount++}
  const keys=ORDER.filter(k=>pt[k]),top=cache?'cache':keys[keys.length-1]||'mac_3b';
  S.hi[top]++;if(top!=='crusoe')S.low++;
  if(cache){S.cache.calls++;S.cache.avoided+=e.tokens_saved||0;S.total+=e.tokens_saved||0}
  for(const k of keys){const u=pt[k],id=k==='crusoe'?k+'|'+u.model:k;
    let r=S.rows.get(id);if(!r){r={k,model:u.model,in:0,out:0,calls:0,usd:0,lat:[]};S.rows.set(id,r)}
    r.model=u.model;r.in+=u.input_tokens||0;r.out+=u.output_tokens||0;r.calls++;r.usd+=u.dollars||0;
    r.lat.push(u.latency_ms||0);if(r.lat.length>500)r.lat.shift();
    S.total+=tokens(u);if(k==='crusoe')S.top+=tokens(u)}
  feedRow(e,pt,keys,cache,top);
}
function feedRow(e,pt,keys,cache,top){
  const row=h('div',null,'call'),a=h('span'),b=h('span'),c=h('span');
  a.append(dotted(top,lab(top)));
  b.textContent=`saved ${f(e.tokens_saved||0)} tok · $${(e.dollars_saved||0).toFixed(5)}`+(e.acceptance_rate_alpha!=null?` · α ${e.acceptance_rate_alpha.toFixed(2)}`:'');
  c.textContent=Math.round(e.latency_ms||0)+' ms';
  const tot=keys.reduce((n,k)=>n+tokens(pt[k]),0);
  const text=cache?'cache hit: 0 model tokens':keys.map(k=>`${T[k].real} ${f(tokens(pt[k]))} tok`).join(' · ');
  const st=h('div',null,'stack'+(tot?'':' none'));st.setAttribute('role','img');st.setAttribute('aria-label','Tokens by tier: '+text);
  for(const k of keys){const i=h('i');i.style.width=(tokens(pt[k])/(tot||1)*100)+'%';i.style.background=`var(${T[k].c})`;i.title=`${T[k].real} (${pt[k].model}): ${f(pt[k].input_tokens)} in, ${f(pt[k].output_tokens)} out`;st.append(i)}
  row.append(a,b,c,st,h('div',text,'brk'));
  $('feed').prepend(row);while($('feed').children.length>60)$('feed').lastChild.remove();
}

function ledger(){
  const body=$('ledbody');body.replaceChildren();
  let tin=0,tout=0,tusd=0;
  for(const k of ORDER){
    const rows=[...S.rows.values()].filter(r=>r.k===k);
    if(k==='cache'){
      const tr=h('tr'),c0=h('td',null,'l');c0.append(dotted(k,lab(k)));
      tr.append(c0,h('td',S.cache.calls?`${T[k].model}; ${f(S.cache.avoided)} tokens avoided`:T[k].model,'l'),h('td','–'),h('td','–'),h('td',S.cache.calls),h('td','–'),h('td','–'));body.append(tr);continue}
    if(!rows.length)rows.push({k,model:T[k].model,in:0,out:0,calls:0,usd:0,lat:[],empty:true});
    for(const r of rows){const tr=h('tr'),c0=h('td',null,'l');c0.append(dotted(k,lab(k)));
      tin+=r.in;tout+=r.out;tusd+=r.usd;
      tr.append(c0,h('td',r.model,'l'),h('td',r.empty?'–':f(r.in)),h('td',r.empty?'–':f(r.out)),h('td',r.calls),
        h('td',k==='crusoe'&&!r.empty?'$'+r.usd.toFixed(5):'–'),h('td',r.empty?'–':f(median(r.lat))));
      body.append(tr)}
  }
  const ft=$('ledfoot');ft.replaceChildren();const tr=h('tr');
  tr.append(h('td','All tiers',null),h('td','',null),h('td',f(tin)),h('td',f(tout)),h('td',S.calls),h('td','$'+tusd.toFixed(5)),h('td',f(median(S.allLat))));ft.append(tr);
}
function donut(){
  const total=S.calls||1;let off=25,out='<circle cx="21" cy="21" r="15.9" fill="none" style="stroke:var(--line)" stroke-width="5"/>';
  for(const k of ORDER){const p=S.hi[k]/total*100;if(p>0){out+=`<circle cx="21" cy="21" r="15.9" fill="none" style="stroke:var(${T[k].c})" stroke-width="5" stroke-dasharray="${p} ${100-p}" stroke-dashoffset="${off}"/>`;off-=p}}
  $('donut').innerHTML=out;
  $('legend').replaceChildren(...ORDER.map(k=>{const d=h('div');d.append(dotted(k,lab(k),h('span',`: ${S.hi[k]} (${Math.round(S.hi[k]/total*100)}%)`)));return d}));
}
function keyLegend(){$('barkey').replaceChildren(...ORDER.filter(k=>k!=='cache').map(k=>dotted(k,h('span',T[k].real))))}

const pad=n=>String(n).padStart(2,'0');
const kept=()=>Math.max(S.total-S.top,0),pct=()=>S.total?kept()/S.total*100:0;
function show(){
  $('tok').textContent=Math.round(D.tok).toLocaleString();$('usd').textContent='$'+D.usd.toFixed(4);$('kept').textContent=Math.round(D.kept).toLocaleString()}
let raf=0;
function ease(){
  D.tok+=(S.tok-D.tok)*.15;D.usd+=(S.usd-D.usd)*.15;D.kept+=(kept()-D.kept)*.15;
  if(Math.abs(S.tok-D.tok)<.5&&Math.abs(S.usd-D.usd)<5e-5&&Math.abs(kept()-D.kept)<.5){D.tok=S.tok;D.usd=S.usd;D.kept=kept();raf=0}else raf=requestAnimationFrame(ease);
  show()}
function paint(){
  if(!raf)raf=requestAnimationFrame(ease);
  $('calls').textContent=S.calls;$('alpha').textContent=S.acount?(S.asum/S.acount).toFixed(2):'–';
  $('progtxt').textContent=`${pad(S.low)} / ${pad(S.calls)}`;
  const p=S.calls?Math.round(S.low/S.calls*100):0;$('progfill').style.width=p+'%';$('progbar').setAttribute('aria-valuenow',p);
  const kp=Math.round(pct());$('keptpct').textContent=kp+'%';$('keptfill').style.width=kp+'%';$('keptbar').setAttribute('aria-valuenow',kp);
  ledger();donut()}
keyLegend();ledger();donut();
// batch paints: a replayed file sends many events at once
let pending=0;
const es=new EventSource('/events');
es.onmessage=m=>{try{addEvent(JSON.parse(m.data))}catch(_){return}if(!pending)pending=setTimeout(()=>{pending=0;paint()},80)};

// ---- benchmarks ----
async function loadBench(){
  const box=$('benchbody');let data;
  try{data=await (await fetch('/api/bench')).json()}catch(e){box.textContent='Could not load /api/bench';return}
  box.replaceChildren();
  if(!data.runs.length){box.textContent='No bench CSVs found.';return}
  for(const run of data.runs){
    const card=h('div',null,'card');card.append(h('h2',run.run+(run.error?' (unreadable: '+run.error+')':''),'serif'));
    const modes=Object.keys(run.modes),base=run.baseline,maxLat=Math.max(...modes.map(m=>run.modes[m].latency_mean_ms||0),1);
    const tcols=['mac_3b','gpu_small','crusoe'].filter(k=>modes.some(m=>(run.modes[m].per_tier||{})[k]));
    const wrap=h('div',null,'wrap'),t=h('table');wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Benchmark '+run.run);
    t.innerHTML='<tr><th>mode</th><th>n</th><th>mean ms</th><th></th><th>quality</th><th>$</th><th>remote tok</th><th>local tok</th>'+tcols.map(k=>`<th>${T[k].real} in / out tok</th>`).join('')+'<th>tiers</th></tr>';
    for(const m of modes){const s=run.modes[m],tr=h('tr');
      const worseL=m!==base&&s.latency_mean_ms>run.modes[base].latency_mean_ms,worseQ=m!==base&&s.quality_mean!=null&&s.quality_mean<run.modes[base].quality_mean;
      tr.append(h('td',m+(m===base?' (baseline)':'')),h('td',s.n),h('td',f(s.latency_mean_ms),worseL?'lose':''));
      const bt=h('td'),bar=h('div',null,'bar');bar.style.width=Math.max(2,(s.latency_mean_ms||0)/maxLat*60)+'px';bt.append(bar);tr.append(bt);
      tr.append(h('td',f(s.quality_mean,2),worseQ?'lose':''),h('td',s.usd?s.usd.toFixed(4):'–'),h('td',f(s.remote_tokens)),h('td',f(s.local_tokens)));
      for(const k of tcols){const u=(s.per_tier||{})[k];tr.append(h('td',u?`${f(u.input_tokens)} / ${f(u.output_tokens)}`:'–'))}
      tr.append(h('td',Object.entries(s.tiers).map(([k,v])=>k+':'+v).join(' ')));
      t.append(tr)}
    wrap.append(t);card.append(wrap);
    const losses=[];
    for(const [cat,ms] of Object.entries(run.categories))for(const m of Object.keys(ms)){
      if(m===base||!ms[base])continue;const a=ms[m],b=ms[base];
      if(a.latency_mean_ms>b.latency_mean_ms)losses.push(`${m} slower on ${cat}: ${f(a.latency_mean_ms)} vs ${f(b.latency_mean_ms)} ms`);
      if(a.quality_mean!=null&&a.quality_mean<b.quality_mean)losses.push(`${m} lower quality on ${cat}: ${f(a.quality_mean,2)} vs ${f(b.quality_mean,2)}`)}
    card.append(h('h2','Where the baseline beat the others','serif'));
    if(losses.length){const ul=h('ul');losses.forEach(l=>ul.append(h('li',l,'lose')));card.append(ul)}else card.append(h('div','None in this run.','dwin'));
    box.append(card)}
}

// ---- Evals tab ----
const EV={d:null,sort:'dataset',dir:1,page:0,PER:25};
const EVCOLS=[['dataset','Benchmark',1],['mode','Mode',1],['top_tokens','Top tokens'],['saved_pct','% saved'],['dollars','$'],['p50_ms','Median ms'],['p90_ms','p90 ms'],['pass_rate','Pass rate'],['n','N']];
const EVTIER=[['cache','Cache','--cache'],['mac','Mac 3B','--mac'],['gpu','GPU','--gpus'],['cloud','Cloud','--crusoe'],['other','Other','--mut']];
const SVGNS='http://www.w3.org/2000/svg';
function sv(tag,attrs,txt){const e=document.createElementNS(SVGNS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(txt!=null)e.textContent=txt;return e}
async function loadEvals(){
  if(EV.d)return;
  try{EV.d=await (await fetch('/api/evals')).json()}catch(_){$('evnote').textContent='Could not load /api/evals.';return}
  if(EV.d.error){$('evnote').textContent='Eval log error: '+EV.d.error;EV.d=null;return}
  const d=EV.d;
  $('evnote').textContent=d.n+' rows from '+new Set(d.rows.map(r=>r.run_id)).size+' result files. Single runs, no repeats; a blank cell means the source file has no such value.';
  const dss=[...new Set(d.leaderboard.map(s=>s.dataset))];
  const opts=(sel,vals,any)=>{sel.replaceChildren(...(any?[new Option('any','')]:[]),...vals.map(v=>new Option(v,v)))};
  opts($('evds'),dss);opts($('fds'),[...new Set(d.rows.map(r=>r.dataset))],true);
  opts($('fmode'),[...new Set(d.rows.map(r=>r.mode))],true);opts($('ftier'),[...new Set(d.rows.map(r=>r.tier).filter(Boolean))],true);
  $('evds').onchange=evCharts;
  for(const i of ['fds','fmode','ftier','fmodel','fpass'])$(i).oninput=()=>{EV.page=0;evLog()};
  $('evprev').onclick=()=>{EV.page--;evLog()};$('evnext').onclick=()=>{EV.page++;evLog()};
  evBoard();evCharts();evLog();
}
function evBoard(){
  const th=$('evlb').tHead;th.replaceChildren();const tr=h('tr');
  for(const [k,t,left] of EVCOLS){const c=h('th',null,left?'l':'num');c.scope='col';
    if(EV.sort===k)c.setAttribute('aria-sort',EV.dir>0?'ascending':'descending');
    const b=h('button',t+(EV.sort===k?(EV.dir>0?' ▲':' ▼'):''));b.type='button';b.onclick=()=>{EV.dir=EV.sort===k?-EV.dir:1;EV.sort=k;evBoard()};c.append(b);tr.append(c)}
  th.append(tr);
  const rows=[...EV.d.leaderboard].sort((a,b)=>{const x=a[EV.sort],y=b[EV.sort];
    if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;   // blanks last either way
    return (typeof x==='string'?x.localeCompare(y):x-y)*EV.dir});
  const tb=$('evlb').tBodies[0];tb.replaceChildren();
  for(const s of rows){const r=h('tr'),bad=k=>s.bad.includes(k);
    const cell=(k,txt)=>{const c=h('td',null,'num');if(bad(k)){c.className+=' lose';c.textContent='▼ '+txt;c.title='Worse than the baseline mode'}else c.textContent=txt;return c};
    const a=h('td',s.dataset,'l'),m=h('td',s.mode,'l');if(s.baseline)m.append(h('span','baseline','ev-base'));
    r.append(a,m,cell('top_tokens',s.top_tokens==null?'–':f(s.top_tokens)),
      cell('saved_pct',s.saved_pct==null?'–':f(s.saved_pct,1)+'%'),cell('dollars',s.dollars==null?'–':'$'+s.dollars.toFixed(5)),
      cell('p50_ms',f(s.p50_ms)),cell('p90_ms',f(s.p90_ms)),cell('pass_rate',s.pass_rate==null?'–':f(s.pass_rate*100,1)+'% of '+s.graded),cell('n',f(s.n)));
    tb.append(r)}
}
function evBars(svg,items,fmt){
  svg.replaceChildren();const W=320,L=62,H=Math.max(40,items.length*26+14),mx=Math.max(...items.map(i=>i.v||0),0);
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.append(sv('line',{x1:L,x2:L,y1:0,y2:H-8,class:'ax'}));
  items.forEach((it,i)=>{const y=6+i*26,w=mx&&it.v?Math.max(2,(W-L-70)*it.v/mx):0;
    svg.append(sv('text',{x:L-6,y:y+13,'text-anchor':'end'},it.k.length>9?it.k.slice(0,8)+'…':it.k));
    if(it.v==null)svg.append(sv('text',{x:L+6,y:y+13},'no data'));
    else{svg.append(sv('rect',{x:L,y,width:w,height:18,rx:2,fill:`var(${it.c})`}));svg.append(sv('text',{x:L+w+5,y:y+13},fmt(it.v)))}});
}
function evCharts(){
  const ds=$('evds').value,lb=EV.d.leaderboard.filter(s=>s.dataset===ds);
  evBars($('evtok'),lb.map(s=>({k:s.mode,v:s.top_tokens,c:s.bad.includes('saved_pct')?'--bad':'--accent'})),v=>f(v));
  evBars($('evusd'),lb.map(s=>({k:s.mode,v:s.dollars,c:s.bad.includes('dollars')?'--bad':'--accent'})),v=>'$'+v.toFixed(5));
  const sv0=$('evstack'),tt=EV.d.tokens_by_tier.filter(t=>t.dataset===ds);sv0.replaceChildren();
  const W=320,L=62,H=tt.length*28+14;sv0.setAttribute('viewBox',`0 0 ${W} ${H}`);
  tt.forEach((t,i)=>{const y=6+i*28,tot=EVTIER.reduce((a,[k])=>a+t[k],0);let x=L;
    sv0.append(sv('text',{x:L-6,y:y+14,'text-anchor':'end'},t.mode.length>9?t.mode.slice(0,8)+'…':t.mode));
    if(!tot){sv0.append(sv('text',{x:L+6,y:y+14},'0 tokens'));return}
    for(const [k,name,c] of EVTIER){if(!t[k])continue;const w=(W-L-6)*t[k]/tot;
      const r=sv('rect',{x,y,width:w,height:20,fill:`var(${c})`});r.append(sv('title',{},`${name}: ${f(t[k])} tokens (${f(100*t[k]/tot,1)}%)`));sv0.append(r);x+=w}});
  $('evkey').replaceChildren(...EVTIER.map(([k,n,c])=>{const s=h('span');const w=h('span',null,'ev-sw');w.style.background=`var(${c})`;s.append(w,n);return s}));
}
function evLog(){
  const v=i=>$(i).value,mq=v('fmodel').toLowerCase();
  const rs=EV.d.rows.filter(r=>(!v('fds')||r.dataset===v('fds'))&&(!v('fmode')||r.mode===v('fmode'))&&(!v('ftier')||r.tier===v('ftier'))
    &&(!mq||(r.model||'').toLowerCase().includes(mq))&&(!v('fpass')||(v('fpass')==='n'?r.passed==null:r.passed===(v('fpass')==='1'))));
  const pages=Math.max(1,Math.ceil(rs.length/EV.PER));EV.page=Math.min(Math.max(0,EV.page),pages-1);
  const tb=$('evlog').tBodies[0];tb.replaceChildren();
  for(const r of rs.slice(EV.page*EV.PER,(EV.page+1)*EV.PER)){const tr=h('tr');
    const n=(x,t)=>h('td',x==null?'–':t,'num');
    tr.append(h('td',r.dataset,'l'),h('td',r.mode,'l'),h('td',r.item_id,'l'),h('td',r.tier||'–','l'),h('td',r.model||'–','l'),n(r.tokens_in,f(r.tokens_in)),n(r.tokens_out,f(r.tokens_out)),
      n(r.dollars,r.dollars==null?'':'$'+r.dollars.toFixed(5)),n(r.latency_ms,f(r.latency_ms)));
    const p=h('td',r.passed==null?'–':r.passed?'pass':'▼ fail','num');if(r.passed===false)p.className+=' lose';tr.append(p);tb.append(tr)}
  $('evpg').textContent=`${rs.length} rows · page ${EV.page+1} of ${pages}`;
  $('evprev').disabled=EV.page<=0;$('evnext').disabled=EV.page>=pages-1;
}
// rooms call Dash.enter(id) when they open; the Ledger loads its tables then
window.Dash={enter:id=>{if(id==='ledger'){loadBench();loadEvals()}}};
})();
