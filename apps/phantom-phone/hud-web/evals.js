/* Evals tab logic. Self-contained: needs the #evals markup (evals.html fragment in index.html) and GET /api/evals.
   Exposes window.loadEvals(). Uses theme CSS variables only (--fg --mut --line --card --bad --accent --cache --mac --gpus --crusoe). */
(()=>{
const $=id=>document.getElementById(id);
function h(tag,txt,cls){const e=document.createElement(tag);if(txt!=null)e.textContent=txt;if(cls)e.className=cls;return e}
const f=(v,d=0)=>v==null?'–':Number(v).toLocaleString(undefined,{maximumFractionDigits:d});

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

window.loadEvals=loadEvals;
})();
