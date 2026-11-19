"""Веб-интерфейс генератора (FastAPI).

Дизайн: светлый enterprise-дашборд в духе CoStar SaaS (без градиентов и
эмодзи-акцентов): левая панель параметров, правая рабочая область,
метрики плитками, таблицы, сдержанный тёмно-синий акцент.

Запуск: .venv/bin/uvicorn app.web:app --host 0.0.0.0 --port 8000
Прод: systemd hse-direct-web.service.

Бесплатный режим по умолчанию: Wordstat не используется, если чекбокс не
включён (нужен ключ в env, API платный).
"""

import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app import ui
from app.metrics import log_run

MAX_JOBS = 3

app = FastAPI(title="Генератор маркетинга на ИИ", docs_url=None, redoc_url=None)
JOBS: dict = {}
JOBS_LOCK = threading.Lock()
OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "web"


def _check_key(request: Request) -> None:
    """Простой доступ по ключу, если WEB_TOKEN задан в env."""
    web_token = os.environ.get("WEB_TOKEN", "")
    if not web_token:
        return
    got = request.query_params.get("key") or request.headers.get("X-Web-Key", "")
    if got != web_token:
        raise HTTPException(status_code=401, detail="нужен ключ доступа (?key=...)")


class WebProgress:
    """Прогресс джобы: пишем этап в JOBS[job_id]['progress'] и номер шага."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def __call__(self, log_line: str) -> None:
        text = ui.stage_text(log_line)
        if text:
            step = 0
            for n, mark in (("1", "Обхожу сайт"), ("2", "Семантика"),
                            ("3", "Тексты"), ("4", "XLSX"), ("3", "gap")):
                if mark in text:
                    step = int(n)
                    break
            with JOBS_LOCK:
                if self.job_id in JOBS:
                    JOBS[self.job_id]["progress"] = text
                    JOBS[self.job_id]["step"] = step or JOBS[self.job_id].get("step", 1)


def _worker(job_id: str, mode: str, url: str, brief: str, region: str,
            use_wordstat: bool, combo: bool) -> None:
    job = JOBS[job_id]
    t0 = time.time()
    try:
        url = url if url.startswith(("http://", "https://")) else "https://" + url
        secs = None
        if mode == "seo":
            from app.seo import run_seo
            res = run_seo(url, brief, region=region, out_dir=str(OUT_DIR),
                          log=WebProgress(job_id))
            job["files"] = [
                ("seo_report.xlsx", res["xlsx"], "SEO-отчёт: ядро, gap, контент-план, meta"),
                ("forecast.txt", res["forecast_txt"], "Медиапрогноз"),
            ] if res["forecast_txt"] else [
                ("seo_report.xlsx", res["xlsx"], "SEO-отчёт"),
            ]
            n_phrases = sum(len(g["rows"]) for g in res["core"])
            job["data"] = {
                "title": "SEO-отчёт готов",
                "meta": "%s · %s" % (url, region),
                "metrics": [
                    {"label": "Фраз в ядре", "value": n_phrases},
                    {"label": "Gap-запросов", "value": len(res["gaps"])},
                    {"label": "Тем контент-плана", "value": len(res["plan"])},
                    {"label": "Время", "value": "%.1f с" % (time.time() - t0)},
                ],
                "table": {
                    "head": ["Тема", "Потенциал, показов/мес", "Формат"],
                    "rows": [[p["title"],
                              "{:,}".format(p["freq"]).replace(",", " "),
                              p["format"]] for p in res["plan"][:8]],
                },
            }
            log_run("seo", url, True, 0, 0)
        elif mode == "forecast":
            from app.seo import run_forecast
            res = run_forecast(url, brief, region=region, out_dir=str(OUT_DIR),
                               log=WebProgress(job_id))
            job["files"] = [("forecast.txt", res["txt"], "Медиапрогноз")]
            t = res["forecast"]["total"]
            job["data"] = {
                "title": "Медиапрогноз готов",
                "meta": "%s · %s" % (url, region),
                "metrics": [
                    {"label": "Показов в месяц", "value": "{:,}".format(t["shows"]).replace(",", " ")},
                    {"label": "Кликов", "value": "{:,}".format(t["clicks"]).replace(",", " ")},
                    {"label": "Бюджет с НДС", "value": "{:,}".format(t["cost"]).replace(",", " ") + " ₽"},
                    {"label": "CPA", "value": "{:,}".format(t["cpa"]).replace(",", " ") + " ₽"},
                ],
                "pre_text": res["text"],
            }
            log_run("forecast", url, True, 0, 0)
        else:
            from app.campaign import generate_campaign
            res = generate_campaign(url, brief, region=region, combo=combo,
                                    out_dir=str(OUT_DIR), log=WebProgress(job_id))
            job["files"] = [
                ("campaign.xlsx", res["xlsx"], "XLSX для Директ Коммандера"),
                ("checklist.txt", res["checklist"], "Чеклист настроек кампании"),
            ]
            groups = res["campaign"]["groups"]
            job["data"] = {
                "title": "Кампания готова",
                "meta": "%s · %s" % (url, region),
                "metrics": [
                    {"label": "Групп", "value": len(groups)},
                    {"label": "Фраз", "value": sum(len(g["phrases"]) for g in groups)},
                    {"label": "Ошибок", "value": len(res["report"]["err"])},
                    {"label": "Время", "value": "%.1f с" % (time.time() - t0)},
                ],
                "table": {
                    "head": ["Группа", "Фраз", "Минус-слова"],
                    "rows": [[g["name"], len(g["phrases"]),
                              " ".join(g["minus_group"]) or "—"] for g in groups],
                },
            }
            log_run("web-campaign", url, not res["report"]["err"],
                    len(res["report"]["err"]), len(res["report"]["warn"]))
        job["status"] = "done"
        job["progress"] = "Готово"
    except Exception as e:
        import traceback
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)[:300]


@app.post("/api/run")
async def api_run(request: Request):
    _check_key(request)
    with JOBS_LOCK:
        running = [j for j in JOBS.values() if j["status"] == "running"]
        if len(running) >= MAX_JOBS:
            return JSONResponse({"error": "сервер занят, попробуй через минуту"},
                                status_code=429)
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"status": "running", "progress": "Запуск...", "step": 1,
                        "files": [], "data": None, "error": "",
                        "ts": time.time()}
    body = await request.json()
    mode = body.get("mode", "campaign")
    if mode not in ("campaign", "seo", "forecast"):
        mode = "campaign"
    url = (body.get("url") or "").strip()
    if "." not in url or " " in url:
        return JSONResponse({"error": "укажи корректный адрес сайта"}, status_code=400)
    threading.Thread(
        target=_worker,
        args=(job_id, mode, url, (body.get("brief") or "").strip(),
              (body.get("region") or ui.DEFAULT_REGION).strip(),
              bool(body.get("wordstat")), bool(body.get("combo", True))),
        daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
async def api_job(job_id: str, request: Request):
    _check_key(request)
    with JOBS_LOCK:
        job = dict(JOBS.get(job_id) or {})
    if not job:
        raise HTTPException(status_code=404, detail="задача не найдена")
    return {
        "status": job["status"],
        "progress": job.get("progress", ""),
        "step": job.get("step", 1),
        "data": job.get("data") if job["status"] == "done" else None,
        "error": job.get("error", ""),
    }


@app.get("/files/{job_id}/{name}")
async def api_file(job_id: str, name: str, request: Request):
    _check_key(request)
    with JOBS_LOCK:
        job = JOBS.get(job_id) or {}
    for fname, path, _ in job.get("files", []):
        if fname == name and Path(path).exists():
            return FileResponse(path, filename=fname)
    raise HTTPException(status_code=404, detail="файл не найден")


@app.get("/api/files/{job_id}")
async def api_files(job_id: str, request: Request):
    _check_key(request)
    with JOBS_LOCK:
        job = dict(JOBS.get(job_id) or {})
    if not job:
        raise HTTPException(status_code=404, detail="задача не найдена")
    return {"files": [{"name": n, "label": lab} for n, _, lab in job.get("files", [])]}


PAGE = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Генератор маркетинга</title>
<style>
:root{--bg:#eef1f6;--panel:#fff;--ink:#16233a;--muted:#5f6b7d;--faint:#8d99ad;
--line:#dce2ec;--accent:#14508c;--accent-soft:#eaf1f9;--ok:#1a7f4b;--err:#b3402e;
--mono:ui-monospace,'SF Mono',Consolas,Menlo,monospace}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,'Segoe UI',Roboto,Arial,sans-serif;min-height:100vh}
a{color:var(--accent)}
.topbar{background:var(--panel);border-bottom:1px solid var(--line);
display:flex;align-items:center;gap:14px;padding:0 28px;height:60px;
position:sticky;top:0;z-index:10}
.mark{width:30px;height:30px;border-radius:7px;background:var(--accent);
color:#fff;display:flex;align-items:center;justify-content:center;
font-weight:700;font-size:13px;letter-spacing:.5px}
.topbar h1{font-size:16px;font-weight:650}
.topbar .sub{color:var(--faint);font-size:12.5px;margin-top:1px}
.badge{margin-left:auto;font-size:11.5px;color:var(--muted);border:1px solid var(--line);
border-radius:99px;padding:4px 12px;background:var(--panel)}
.layout{display:grid;grid-template-columns:360px 1fr;gap:24px;
max-width:1180px;margin:28px auto 60px;padding:0 24px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:22px;position:sticky;top:84px}
.panel h2{font-size:13px;font-weight:650;letter-spacing:.8px;
text-transform:uppercase;color:var(--muted);margin-bottom:14px}
.seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;margin-bottom:18px}
.seg button{flex:1;padding:10px 4px;background:var(--panel);border:none;
font:600 12.5px/1.2 inherit;color:var(--muted);cursor:pointer;transition:.12s}
.seg button+button{border-left:1px solid var(--line)}
.seg button.on{background:var(--accent);color:#fff}
.field{margin-bottom:16px}
.field label{display:block;font-size:11.5px;font-weight:650;letter-spacing:.6px;
text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.field input,.field select{width:100%;padding:10px 12px;border:1px solid var(--line);
border-radius:8px;font:15px inherit;color:var(--ink);background:var(--panel);outline:none}
.field input:focus,.field select:focus{border-color:var(--accent);
box-shadow:0 0 0 3px var(--accent-soft)}
.hint{font-size:12px;color:var(--faint);margin-top:5px}
.toggle{display:flex;align-items:flex-start;gap:10px;padding:12px;
border:1px solid var(--line);border-radius:8px;cursor:pointer;margin:4px 0 16px}
.toggle input{margin-top:2px}
.toggle .t{font-size:13.5px;font-weight:600}
.toggle .d{font-size:12px;color:var(--faint)}
.cta{width:100%;padding:13px;border:none;border-radius:8px;background:var(--accent);
color:#fff;font:650 15px inherit;cursor:pointer}
.cta:hover{background:#0f4276}
.cta:disabled{opacity:.45;cursor:not-allowed}
.linkrow{text-align:center;margin-top:12px;font-size:13px}
.linkrow a{cursor:pointer;text-decoration:none;border-bottom:1px dashed var(--accent)}
.workspace{min-height:420px}
.empty{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:48px 32px;text-align:center;color:var(--muted)}
.empty .big{font-size:17px;font-weight:650;color:var(--ink);margin-bottom:8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:22px}
.mt{margin-top:16px}
.steps{display:flex;gap:0;margin-bottom:22px;list-style:none;padding:0}
.steps li{flex:1;text-align:center;font-size:12px;color:var(--faint);
padding-bottom:10px;border-bottom:2px solid var(--line)}
.steps li.on{color:var(--accent);border-color:var(--accent);font-weight:600}
.steps li.done{color:var(--ok);border-color:var(--ok)}
.result-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.result-head .t{font-size:18px;font-weight:700;color:var(--ok)}
.result-head .meta{font-size:13px;color:var(--faint)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-top:18px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .l{font-size:11px;font-weight:650;letter-spacing:.6px;text-transform:uppercase;color:var(--faint)}
.tile .v{font-size:22px;font-weight:700;margin-top:4px}
table{width:100%;border-collapse:collapse;margin-top:18px;font-size:13.5px}
th{text-align:left;font-size:11px;font-weight:650;letter-spacing:.6px;
text-transform:uppercase;color:var(--muted);padding:9px 12px;
border-bottom:1px solid var(--line);background:#f7f9fc}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
td.num{font-family:var(--mono);white-space:nowrap}
.files .row{display:flex;align-items:center;gap:14px;padding:13px 4px;
border-bottom:1px solid var(--line)}
.files .row:last-child{border-bottom:none}
.files .ext{font:700 10.5px/1 var(--mono);color:var(--accent);background:var(--accent-soft);
padding:5px 7px;border-radius:5px;letter-spacing:.5px}
.files .name{font-weight:650;font-size:14px}
.files .lab{font-size:12px;color:var(--faint)}
.files .dl{margin-left:auto;font-size:13px;font-weight:600;text-decoration:none}
pre{background:#f7f9fc;border:1px solid var(--line);border-radius:8px;
padding:14px;font:12.5px/1.55 var(--mono);overflow-x:auto;margin-top:16px;color:var(--ink)}
.errbox{display:none;background:#fbf1ef;border:1px solid #e6c4bd;
border-radius:10px;padding:16px;color:var(--err);margin-top:16px}
@media(max-width:900px){.layout{grid-template-columns:1fr}.panel{position:static}}
</style>
</head><body>
<div class="topbar">
  <div class="mark">ДГ</div>
  <div><h1>Генератор маркетинга</h1>
  <div class="sub">кампания Директа, SEO-отчёт, медиапрогноз</div></div>
  <div class="badge">ВШЭ · ИИ в маркетинге</div>
</div>

<div class="layout">
  <div class="panel">
    <h2>Параметры</h2>
    <div class="seg">
      <button class="on" data-mode="campaign" onclick="setMode(this)">Кампания</button>
      <button data-mode="seo" onclick="setMode(this)">SEO</button>
      <button data-mode="forecast" onclick="setMode(this)">Прогноз</button>
    </div>
    <div class="field"><label>Сайт</label>
      <input type="text" id="url" placeholder="kuppersberg.ru" autocomplete="off">
      <div class="hint">duplex-shop.ru, kuppersberg.ru или любой сайт</div></div>
    <div class="field"><label>Тема (бриф)</label>
      <input type="text" id="brief" placeholder="встраиваемая техника" autocomplete="off">
      <div class="hint">можно оставить пустым</div></div>
    <div class="field"><label>Регион</label>
      <select id="region">
        <option>Москва и область</option><option>Россия</option>
      </select></div>
    <div class="toggle" onclick="event.preventDefault();$('wordstat').click()">
      <input type="checkbox" id="wordstat">
      <div><div class="t">Wordstat API</div>
      <div class="d">живые частоты запросов; без ключа работает встроенная модель</div></div>
    </div>
    <div class="toggle" onclick="event.preventDefault();$('combo').click()">
      <input type="checkbox" id="combo" checked>
      <div><div class="t">Комбинаторика</div>
      <div class="d">каждому объявлению 7 заголовков и 3 текста</div></div>
    </div>
    <button class="cta" id="go" onclick="run()">Сформировать</button>
    <div class="linkrow"><a onclick="demo()">Пример: kuppersberg.ru · встраиваемая техника</a></div>
  </div>

  <div class="workspace">
    <div class="empty" id="empty">
      <div class="big">Результат появится здесь</div>
      Заполни параметры слева и нажми «Сформировать».<br>
      Сборка занимает около 10 секунд.
    </div>

    <div id="work" style="display:none">
      <ol class="steps">
        <li id="s1">Обход сайта</li><li id="s2">Семантика</li>
        <li id="s3">Тексты</li><li id="s4">Файлы</li>
      </ol>
      <div class="card" id="runbox">
        <div id="ptext" style="font-size:14px;color:var(--muted)">Запуск…</div>
      </div>
    </div>

    <div id="result" style="display:none"></div>
    <div class="errbox" id="err"></div>
  </div>
</div>

<script>
let MODE='campaign',KEY=new URLSearchParams(location.search).get('key')||'';
const $=id=>document.getElementById(id);
const KEYQ=KEY?'?key='+KEY:'';
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function setMode(b){document.querySelectorAll('.seg button').forEach(x=>x.classList.remove('on'));
b.classList.add('on');MODE=b.dataset.mode;
$('s3').textContent=MODE==='campaign'?'Тексты':(MODE==='seo'?'Gap-анализ':'Прогноз');}
function demo(){$('url').value='kuppersberg.ru';$('brief').value='встраиваемая техника';run();}
function steps(n){for(let i=1;i<=4;i++){const el=$('s'+i);
el.className=n>i?'done':(n===i?'on':'');}}
async function run(){
 const url=$('url').value.trim();
 if(!url){$('url').focus();return;}
 $('go').disabled=true;$('err').style.display='none';
 $('empty').style.display='none';$('result').style.display='none';
 $('work').style.display='block';steps(1);$('ptext').textContent='Запуск…';
 const r=await fetch('/api/run'+KEYQ,{method:'POST',
   headers:{'Content-Type':'application/json'},
   body:JSON.stringify({mode:MODE,url:url,brief:$('brief').value.trim(),
     region:$('region').value,wordstat:$('wordstat').checked,combo:$('combo').checked})});
 const j=await r.json();
 if(!r.ok){fail(j.detail||j.error||'ошибка');return;}
 const timer=setInterval(()=>{
   fetch('/api/job/'+j.job_id+KEYQ).then(r=>r.json()).then(job=>{
     $('ptext').innerHTML=job.progress||'…';
     steps(job.status==='done'?5:(job.step||1));
     if(job.status==='done'){clearInterval(timer);show(j.job_id);}
     if(job.status==='error'){clearInterval(timer);fail(job.error);}
   }).catch(()=>{});
 },1200);
}
async function show(jobId){
 $('go').disabled=false;$('work').style.display='none';$('result').style.display='block';
 const job=await(await fetch('/api/job/'+jobId+KEYQ)).json();
 const d=job.data;
 let h='<div class="card"><div class="result-head"><span class="t">'+esc(d.title)+
   '</span><span class="meta">'+esc(d.meta)+'</span></div>';
 h+='<div class="tiles">'+d.metrics.map(m=>'<div class="tile"><div class="l">'+
   esc(m.label)+'</div><div class="v">'+esc(m.value)+'</div></div>').join('')+'</div>';
 if(d.table){
   h+='<table><thead><tr>'+d.table.head.map(x=>'<th>'+esc(x)+'</th>').join('')+
      '</tr></thead><tbody>'+d.table.rows.map(r=>'<tr>'+r.map((c,i)=>
      '<td'+(i>0&&/^\\d/.test(c)?' class="num"':'')+'>'+esc(c)+'</td>').join('')+
      '</tr>').join('')+'</tbody></table>';
 }
 if(d.pre_text){h+='<pre>'+esc(d.pre_text)+'</pre>';}
 h+='</div>';
 const fl=await(await fetch('/api/files/'+jobId+KEYQ)).json();
 h+='<div class="card mt files">'+fl.files.map(f=>'<div class="row"><span class="ext">'+
   f.name.split('.').pop().toUpperCase()+'</span><div><div class="name">'+esc(f.name)+
   '</div><div class="lab">'+esc(f.label)+'</div></div>'+
   '<a class="dl" href="/files/'+jobId+'/'+f.name+KEYQ+'">Скачать</a></div>').join('')+'</div>';
 $('result').innerHTML=h;
}
function fail(msg){$('go').disabled=false;$('work').style.display='none';
 $('err').style.display='block';$('err').textContent=msg;}
</script></body></html>"""


@app.get("/")
async def index(request: Request):
    _check_key(request)
    return HTMLResponse(PAGE)
