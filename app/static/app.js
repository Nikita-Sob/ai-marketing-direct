/* Генератор маркетинга · фронт. Ванилла, без зависимостей.
   Состояния: hero -> run (живой журнал по реальному логу джобы) -> result. */
(() => {
const $ = id => document.getElementById(id);
const KEY = new URLSearchParams(location.search).get('key') || '';
const KQ = KEY ? '?key=' + encodeURIComponent(KEY) : '';
const esc = s => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt = n => Math.round(n).toLocaleString('ru-RU').replace(/\u00a0/g,' ');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;

const MODES = {
  campaign: {kick:'Кампания Директа', stages:[['Обход сайта','бренд, каталог, УТП'],['Семантика','фразы и минус-слова'],['Объявления','заголовки и тексты'],['Файлы','XLSX и валидация']]},
  seo:      {kick:'SEO-отчёт',       stages:[['Обход сайта','бренд, каталог, УТП'],['Ядро','фразы с частотами'],['Gap-анализ','незакрытый спрос'],['Отчёт','XLSX и прогноз']]},
  forecast: {kick:'Медиапрогноз',    stages:[['Обход сайта','бренд, каталог'],['Спрос','частоты по группам'],['Модель','CTR, CPC, конверсия'],['Отчёт','текст и файл']]},
};
let MODE = 'campaign', REGION = 'Москва и область', busy = false;

/* ---------- ввод ---------- */
const modes = $('modes'), ind = $('segInd');
function placeInd(){ const b = modes.querySelector('.on'); ind.style.width = b.offsetWidth+'px'; ind.style.transform = `translateX(${b.offsetLeft-3}px)`; }
modes.addEventListener('click', e => {
  const b = e.target.closest('button'); if(!b) return;
  modes.querySelectorAll('button').forEach(x => x.classList.toggle('on', x===b));
  MODE = b.dataset.mode; placeInd();
  $('go').querySelector('.go-t').textContent = {campaign:'Сформировать', seo:'Построить отчёт', forecast:'Посчитать'}[MODE];
});
$('region').addEventListener('click', e => {
  const b = e.target.closest('.chip'); if(!b) return;
  $('region').querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x===b)); REGION = b.dataset.v;
});
document.querySelectorAll('.ex').forEach(b => b.addEventListener('click', () => {
  typeInto($('url'), b.dataset.url).then(() => typeInto($('brief'), b.dataset.brief)).then(() => setTimeout(run, 250));
}));
async function typeInto(el, text){
  el.value = ''; el.focus();
  if (RM) { el.value = text; return; }
  for (const ch of text){ el.value += ch; await sleep(18 + Math.random()*26); }
}
$('url').addEventListener('input', e => { e.target.value = e.target.value.replace(/^https?:\/\//,''); });
addEventListener('keydown', e => {
  if (e.key === '/' && document.activeElement.tagName !== 'INPUT'){ e.preventDefault(); if(!busy){ reset(); setTimeout(()=>$('url').focus(), 50);} }
});
addEventListener('scroll', () => document.body.classList.toggle('scrolled', scrollY > 8), {passive:true});
addEventListener('resize', placeInd);
document.fonts && document.fonts.ready.then(placeInd); placeInd();

function toast(msg){ const t = $('toast'); t.innerHTML = '<b>Ошибка</b>'+esc(msg); t.classList.add('show'); clearTimeout(t._t); t._t = setTimeout(()=>t.classList.remove('show'), 5200); }

/* ---------- переходы ---------- */
async function swapTo(showId){
  const cur = ['hero','run','result'].map($).find(x => !x.hidden);
  const next = $(showId);
  if (cur === next) return;
  if (cur && !RM){ cur.classList.add('out'); await sleep(380); cur.classList.remove('out'); }
  if (cur) cur.hidden = true;
  next.hidden = false; scrollTo({top:0});
  next.querySelectorAll('.reveal').forEach(el => { el.style.animation='none'; el.offsetHeight; el.style.animation=''; });
}
function reset(){ if (busy) return; document.body.classList.remove('has-run'); swapTo('hero'); setTimeout(()=>{placeInd(); $('url').focus();}, 420); }

/* ---------- запуск ---------- */
async function run(){
  if (busy) return;
  const url = $('url').value.trim().replace(/^https?:\/\//,'').replace(/\/$/,'');
  if (!url || !url.includes('.')){ const c=$('cmd'); c.classList.remove('shake'); c.offsetWidth; c.classList.add('shake'); $('url').focus(); return; }
  busy = true; $('go').disabled = true;
  let r, j;
  try {
    r = await fetch('/api/run'+KQ, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({mode:MODE, url, brief:$('brief').value.trim(), region:REGION,
        wordstat:$('wordstat').checked, combo:$('combo').checked})});
    j = await r.json();
  } catch(e){ j = {error:'сервер недоступен'}; r = {ok:false}; }
  if (!r.ok){ busy=false; $('go').disabled=false; toast(j.detail || j.error || 'не удалось запустить'); return; }

  buildRun(url);
  document.body.classList.add('busy','has-run'); $('sysStatus').textContent = 'Генерация';
  await swapTo('run');
  const res = await follow(j.job_id);
  document.body.classList.remove('busy'); $('sysStatus').textContent = 'Система готова';
  busy = false; $('go').disabled = false;
  if (res.status === 'done'){ await sleep(550); renderResult(j.job_id, res, url); await swapTo('result'); observe(); countUp(); }
  else { await swapTo('hero'); toast(res.error || 'генерация не удалась'); }
}

/* ---------- экран процесса ---------- */
let stageN = 0, ctr = {};
function buildRun(url){
  const m = MODES[MODE];
  $('runKicker').innerHTML = '<span class="dot"></span>'+m.kick+' · '+esc(REGION);
  $('runTitle').textContent = url;
  $('timer').innerHTML = '0.0<small>с</small>';
  $('stages').innerHTML = m.stages.map((s,i)=>`<li class="stage" id="st${i+1}"><span class="sn">0${i+1}</span>
    <span class="ck"><svg viewBox="0 0 12 12"><path d="M2.5 6.2l2.4 2.4 4.6-4.9"/></svg></span>
    <div class="st">${s[0]}</div><div class="sd">${s[1]}</div><i class="bar"></i></li>`).join('');
  $('navSteps').innerHTML = '<span></span><span></span><span></span><span></span>';
  $('feed').innerHTML = '';
  ctr = {brand:'', cats:0, groups:0, phrases:0, last:''};
  const labels = MODE==='campaign' ? ['Категорий найдено','Групп объявлений','Ключевых фраз']
    : MODE==='seo' ? ['Категорий найдено','Групп ядра','Фраз в ядре'] : ['Категорий найдено','Групп спроса','Статус'];
  $('counters').innerHTML = labels.map((l,i)=>`<div class="ctr"><div class="ctr-l">${l}</div><div class="ctr-v zero" id="cv${i}">0</div><div class="ctr-s" id="cs${i}"></div></div>`).join('');
  if (MODE==='forecast') { $('cv2').textContent='…'; }
  stageN = 0; setStage(1);
}
function setStage(n){
  if (n <= stageN) return; stageN = n;
  for (let i=1;i<=4;i++){ const el=$('st'+i); if(!el) continue; el.className='stage'+(i<n?' done':i===n?' on':''); }
  $('navSteps').querySelectorAll('span').forEach((s,i)=>s.className = i+1<n?'done':i+1===n?'on':'');
}
function setCtr(i, v, sub){
  const el = $('cv'+i); if (!el) return;
  const from = parseInt(el.dataset.v||'0',10); el.dataset.v = v; el.classList.toggle('zero', !v);
  tween(from, v, 500, x => el.textContent = fmt(x));
  if (sub != null) $('cs'+i).textContent = sub;
}
function tween(a, b, ms, cb){
  if (RM || a===b){ cb(b); return; }
  const t0 = performance.now();
  const f = t => { const p = Math.min(1,(t-t0)/ms), e = 1-Math.pow(1-p,4); cb(a+(b-a)*e); if(p<1) requestAnimationFrame(f); };
  requestAnimationFrame(f);
}

const prettify = (s) => {
  s = s.replace(/^\s+/,'');
  let m;
  if ((m = s.match(/^(\d)\/(\d) (.*)$/))) return {h:true, t:`<span class="tag">[${m[1]}/${m[2]}]</span> ${esc(m[3])}`, stage:+m[1]};
  if ((m = s.match(/^бренд: (.*?); категорий: (\d+); УТП: (\d+)/))) return {t:`бренд <b>${esc(m[1])}</b> · категорий ${m[2]} · УТП ${m[3]}`, brand:m[1], cats:+m[2]};
  if ((m = s.match(/^группа (\S+): (\d+) фраз/))) return {t:`группа <b>${esc(m[1].replace(/_/g,' '))}</b> · ${m[2]} фраз`, group:m[1], ph:+m[2]};
  if ((m = s.match(/^групп: (\d+), фраз: (\d+)/))) return {t:`ядро: групп ${m[1]}, фраз ${m[2]}`, coreG:+m[1], coreP:+m[2]};
  if ((m = s.match(/^wordstat (.*?): (\d+) фраз/))) return {t:`wordstat · <b>${esc(m[1])}</b> · ${m[2]} фраз`, ws:m[1], wsp:+m[2]};
  if ((m = s.match(/^(готово за [\d.]+ c|прогноз готов)/))) return {ok:true, t:esc(m[1].replace(' c',' с'))};
  if (/^WARN/.test(s)) return {t:'<span style="color:var(--warn)">'+esc(s)+'</span>'};
  return {t:esc(s.replace(/\/root\/\S+\//g,''))};
};

function pushLine(tSec, raw){
  const p = prettify(raw);
  const feed = $('feed');
  const d = document.createElement('div');
  d.className = 'fl'+(p.h?' h':'')+(p.ok?' ok':'');
  d.innerHTML = `<span class="ft">${tSec.toFixed(2)}</span><span class="fx">${p.t}</span>`;
  const caret = feed.querySelector('.caret'); if (caret) caret.parentElement.remove();
  feed.appendChild(d);
  const cl = document.createElement('div'); cl.className='fl'; cl.innerHTML='<span class="ft"></span><span class="fx"><i class="caret"></i></span>'; feed.appendChild(cl);
  while (feed.children.length > 40) feed.firstChild.remove();
  if (p.stage) setStage(MODE==='seo' && p.stage===3 ? 3 : p.stage);
  if (/^(4\/4|прогноз готов|готово)/.test(raw.trim())) setStage(4);
  if (p.cats != null){ ctr.cats=p.cats; setCtr(0, p.cats, 'бренд: '+p.brand); }
  if (p.group){ ctr.groups++; ctr.phrases+=p.ph; setCtr(1, ctr.groups, p.group.replace(/_/g,' ')); setCtr(2, ctr.phrases, '+'+p.ph+' из группы'); }
  if (p.coreG != null){ setCtr(1, p.coreG); setCtr(2, p.coreP); }
  if (p.ws){ ctr.groups++; ctr.phrases+=p.wsp; setCtr(1, ctr.groups, p.ws); if(MODE==='seo') setCtr(2, ctr.phrases); }
}

async function follow(jobId){
  const t0 = performance.now(); let shown = 0, queue = [], last = null, done = false, fake = 0;
  const tick = setInterval(() => { $('timer').innerHTML = ((performance.now()-t0)/1000).toFixed(1)+'<small>с</small>'; }, 50);
  // показ строк с ритмом: реальные строки приходят пачками, отдаём их по одной
  const pump = (async () => {
    while (!done || queue.length){
      if (queue.length){ const [t, s] = queue.shift(); pushLine(t, s); await sleep(RM?0:(queue.length>6?70:150)); }
      else await sleep(60);
    }
  })();
  while (true){
    try {
      const job = await (await fetch('/api/job/'+jobId+KQ)).json();
      const log = job.log || [];
      // берём только новые строки лога
      for (const row of log.slice(shown)) queue.push(row);
      shown = log.length;
      if (!log.length && job.status==='running'){ // прогноз без Wordstat почти не логирует
        fake++; if (fake===3) setStage(2); if (fake===6) setStage(3);
      }
      if (job.status !== 'running'){ last = job; break; }
    } catch(e){}
    await sleep(350);
  }
  done = true; await pump; clearInterval(tick);
  if (last.status==='done'){
    if (MODE==='forecast'){ const g=(last.data.groups||[]).length; setCtr(0,(last.data.card.categories||[]).length,'бренд: '+last.data.card.brand); setCtr(1,g); $('cv2').textContent='готово'; $('cv2').classList.remove('zero'); }
    pushLine((performance.now()-t0)/1000, 'Файлы готовы к скачиванию');
    setStage(5); $('navSteps').querySelectorAll('span').forEach(s=>s.className='done');
  }
  return last;
}

/* ---------- результат ---------- */
const IC = {
  dl:'<svg viewBox="0 0 24 24"><path d="M12 4v12m0 0l-5-5m5 5l5-5M5 20h14"/></svg>',
  ok:'<svg viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7"/></svg>',
  back:'<svg viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6"/></svg>',
};
let RES = null, JOB = '';
function kpi(label, value, sub, cls){
  const s = String(value); const m = s.match(/^([\d\s.,]+)(.*)$/);
  const num = m ? parseFloat(m[1].replace(/\s/g,'').replace(',','.')) : null;
  const dec = m && /[.,]\d/.test(m[1]) ? 1 : 0;
  return `<div class="kpi"><div class="kpi-l">${esc(label)}</div>
    <div class="kpi-v ${cls||''}" ${num!=null?`data-n="${num}" data-dec="${dec}"`:''}>${num!=null?'0':esc(s)}${m&&m[2].trim()?'<small>'+esc(m[2].trim())+'</small>':''}</div>
    ${sub?`<div class="kpi-s">${esc(sub)}</div>`:''}</div>`;
}
function countUp(){
  document.querySelectorAll('.kpi-v[data-n]').forEach((el,i) => {
    const n = +el.dataset.n, dec = +el.dataset.dec, small = el.querySelector('small');
    const node = document.createTextNode('0'); el.firstChild.replaceWith(node);
    setTimeout(() => tween(0, n, 1100, x => node.textContent = dec ? x.toFixed(1).replace('.',',') : fmt(x)), 120 + i*90);
  });
}
function observe(){
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting){ e.target.classList.add('inview'); io.unobserve(e.target);} }), {threshold:.12});
  document.querySelectorAll('.stagger,.bars').forEach(el => { [...el.children].forEach((c,i)=>c.style.setProperty('--i',Math.min(i,12))); io.observe(el); });
}
function head(title, dim, url, extra){
  return `<div class="r-head reveal" style="--d:0"><div>
    <span class="r-badge">${IC.ok}Готово за ${esc(String(RES.elapsed ?? '').replace('.',','))} с · валидация пройдена</span>
    <h1 class="r-title">${title} <span class="dim">${dim}</span></h1>
    <div class="r-meta"><span class="mono">${esc(url)}</span><span>${esc(REGION)}</span>${extra||''}</div></div>
    <div class="r-actions"><button class="btn btn-g" onclick="App.reset()">${IC.back}Новый запрос</button>
    ${FILES[0]?`<a class="btn btn-p" href="${FILES[0].href}">${IC.dl}${esc(FILES[0].name.split('.').pop().toUpperCase())}</a>`:''}</div></div>`;
}
function sec(n, t, s, body){ return `<section class="sec reveal" style="--d:${n+1}"><div class="sec-h"><div class="sec-t"><span class="sec-n">0${n}</span>${t}</div><div class="sec-s">${s||''}</div></div>${body}</section>`; }
function siteSec(card){
  return `<div class="site">${(card.categories||[]).map(c=>`<span class="c">${esc(c.name)}</span>`).join('')}</div>`;
}
function filesBlock(){
  return `<div class="files stagger">${FILES.map(f=>`<a class="file" href="${f.href}"><span class="file-ic">${esc(f.name.split('.').pop().toUpperCase())}</span>
    <div><div class="file-n">${esc(f.name)}</div><div class="file-l">${esc(f.label)}</div></div><span class="file-d">${IC.dl}</span></a>`).join('')}</div>`;
}
let FILES = [];
async function renderResult(jobId, job, url){
  JOB = jobId; RES = job.data;
  try { FILES = (await (await fetch('/api/files/'+jobId+KQ)).json()).files.map(f => ({...f, href:'/files/'+jobId+'/'+encodeURIComponent(f.name)+KQ})); } catch(e){ FILES=[]; }
  const d = RES, M = d.metrics || [], card = d.card || {};
  let h = '';
  if (MODE === 'campaign'){
    const groups = d.groups || [];
    const err = +M[2].value;
    h += head('Кампания', 'готова к загрузке', url, card.brand?`<span>бренд <b>${esc(card.brand)}</b></span>`:'');
    h += `<div class="kpis reveal" style="--d:1">${kpi('Групп объявлений', M[0].value, 'по категориям сайта')}${kpi('Ключевых фраз', M[1].value, '+ автотаргетинг в каждой')}
      ${kpi('Ошибок валидации', M[2].value, err?'проверь чеклист':'файл примет Коммандер', err?'':'good')}${kpi('Время сборки', M[3].value, 'вместо ~2,5 ч вручную')}</div>`;
    h += sec(1, 'Группы и объявления', 'так объявление увидят в выдаче', `<div class="groups"><div class="g-list" id="glist">${groups.map((g,i)=>
      `<button class="g-item${i?'':' on'}" data-i="${i}"><span class="gi-n">${String(i+1).padStart(2,'0')}</span><span class="gi-t">${esc(g.name)}</span><span class="gi-c">${g.phrases.length}</span></button>`).join('')}
      </div><div class="g-detail" id="gdetail"></div></div>`);
    h += sec(2, 'Что нашли на сайте', (card.categories||[]).length+' категорий', siteSec(card));
    h += sec(3, 'Файлы', 'XLSX импортируется в Директ Коммандер', filesBlock());
  } else if (MODE === 'seo'){
    h += head('SEO-отчёт', 'собран', url);
    h += `<div class="kpis reveal" style="--d:1">${kpi(M[0].label, M[0].value)}${kpi(M[1].label, M[1].value, 'спрос без страницы на сайте')}${kpi(M[2].label, M[2].value)}${kpi(M[3].label, M[3].value)}</div>`;
    const gaps = d.gaps || [], gmax = Math.max(1, ...gaps.map(g=>g.freq));
    h += sec(1, 'Незакрытый спрос', 'запросы, под которые на сайте нет страницы', `<div class="panel"><table class="tbl"><thead><tr><th>Запрос</th><th>Группа</th><th></th><th style="text-align:right">Показов/мес</th></tr></thead>
      <tbody class="bars stagger">${gaps.slice(0,12).map(g=>`<tr><td>${esc(g.phrase)}</td><td style="text-transform:capitalize">${esc(g.group.replace(/_/g,' '))}</td><td><div class="barc"><i style="--w:${(g.freq/gmax).toFixed(3)}"></i></div></td><td class="r">${fmt(g.freq)}</td></tr>`).join('')}</tbody></table></div>`);
    const plan = d.plan || [];
    h += sec(2, 'Контент-план', 'темы по потенциалу трафика', `<div class="panel"><table class="tbl"><thead><tr><th>Тема</th><th>Структура</th><th>Формат</th><th style="text-align:right">Потенциал</th></tr></thead>
      <tbody class="stagger">${plan.map(p=>`<tr><td>${esc(p.title)}</td><td style="color:var(--fg-3);font-size:13px">${esc((p.structure||[]).slice(0,3).join(' · '))}</td><td><span class="fmt">${esc(p.format)}</span></td><td class="r">${fmt(p.freq)}</td></tr>`).join('')}</tbody></table></div>`);
    const core = d.core || [];
    h += sec(3, 'Семантическое ядро', core.length+' групп', `<div class="combo stagger">${core.map(g=>`<div><div class="lbl" style="margin-top:0;text-transform:none;letter-spacing:0;font-size:13px;color:var(--fg)">${esc(g.name)}</div><ol>${g.rows.slice(0,6).map(r=>`<li>${esc(r[0])}<span class="len">${r[1]?fmt(r[1]):'—'}</span></li>`).join('')}</ol></div>`).join('')}</div>`);
    h += sec(4, 'Файлы', '', filesBlock());
  } else {
    const t = d.total || {}, gr = d.groups || [], cmax = Math.max(1, ...gr.map(g=>g.cost));
    h += head('Медиапрогноз', 'на месяц', url);
    h += `<div class="kpis reveal" style="--d:1">${kpi('Показов в месяц', fmt(t.shows))}${kpi('Кликов', fmt(t.clicks), 'CTR '+((d.params||{}).ctr*100||0).toFixed(1).replace('.',',')+'%')}${kpi('Бюджет с НДС', fmt(t.cost)+' ₽')}${kpi('CPA', fmt(t.cpa)+' ₽', 'конверсий: '+String(t.conv).replace('.',','))}</div>`;
    h += sec(1, 'Прогноз по группам', 'бюджет пропорционален спросу', `<div class="panel"><table class="tbl"><thead><tr><th>Группа</th><th></th><th style="text-align:right">Показы</th><th style="text-align:right">Клики</th><th style="text-align:right">Бюджет, ₽</th><th style="text-align:right">CPA, ₽</th></tr></thead>
      <tbody class="bars stagger">${gr.map(g=>`<tr><td style="text-transform:capitalize">${esc(g.name.replace(/_/g,' '))}</td><td><div class="barc"><i style="--w:${(g.cost/cmax).toFixed(3)}"></i></div></td><td class="r">${fmt(g.shows)}</td><td class="r">${fmt(g.clicks)}</td><td class="r">${fmt(g.cost)}</td><td class="r">${fmt(g.cpa)}</td></tr>`).join('')}</tbody></table></div>`);
    h += sec(2, 'Допущения модели', 'заменяются данными из Директа', `<div class="pre">${esc(d.pre_text||'')}</div>`);
    h += sec(3, 'Файлы', '', filesBlock());
  }
  $('result').innerHTML = h;
  if (MODE === 'campaign'){
    $('glist').addEventListener('click', e => { const b = e.target.closest('.g-item'); if(!b) return;
      $('glist').querySelectorAll('.g-item').forEach(x=>x.classList.toggle('on', x===b)); showGroup(+b.dataset.i, true); });
    showGroup(0, false);
  }
}
function showGroup(i, anim){
  const g = RES.groups[i], a = g.ad, dom = (a.link||'').replace(/^https?:\/\//,'').split('/')[0];
  const el = $('gdetail');
  el.innerHTML = `<div class="gd-h"><div class="gd-t">${esc(g.name)}</div><div class="gd-c">группа ${String(i+1).padStart(2,'0')} / ${String(RES.groups.length).padStart(2,'0')}</div></div>
    <div class="lbl">Объявление в выдаче</div>
    <div class="serp"><div class="serp-top"><span class="serp-fav">${esc(dom[0]||'')}</span><span class="serp-dom">${esc(dom)}</span><span class="serp-ad">Реклама</span></div>
      <div class="serp-h">${esc(a.h1)}${a.h2?' / '+esc(a.h2):''}</div><div class="serp-t">${esc(a.text)}</div>
      ${a.utochneniya.length?`<div class="serp-u">${a.utochneniya.map(u=>'<span>'+esc(u)+'</span>').join('')}</div>`:''}
      ${a.quick_links.length?`<div class="serp-q">${a.quick_links.map(q=>'<span>'+esc(q)+'</span>').join('')}</div>`:''}</div>
    ${a.combo_heads.length?`<div class="combo" style="margin-top:8px"><div><div class="lbl">Заголовки · ${a.combo_heads.length}</div><ol>${a.combo_heads.map(x=>`<li>${esc(x)}<span class="len">${x.length}/56</span></li>`).join('')}</ol></div>
      <div><div class="lbl">Тексты · ${a.combo_texts.length}</div><ol>${a.combo_texts.map(x=>`<li>${esc(x)}<span class="len">${x.length}/81</span></li>`).join('')}</ol></div></div>`:''}
    <div class="lbl">Ключевые фразы · ${g.phrases.length}</div><div class="tags">${g.phrases.map(p=>`<span class="tag-k">${esc(p)}</span>`).join('')}</div>
    ${g.minus.length?`<div class="lbl">Кросс-минусовка</div><div class="tags">${g.minus.map(p=>`<span class="tag-m">${esc(p)}</span>`).join('')}</div>`:''}`;
  if (anim && !RM){ el.classList.remove('swap'); el.offsetWidth; el.classList.add('swap'); }
}

window.App = {run, reset};
})();
