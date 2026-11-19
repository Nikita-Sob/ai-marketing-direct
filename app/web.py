"""Веб-интерфейс генератора (FastAPI).

Один экран: выбор режима, ссылка, бриф, регион; живой прогресс опросом
/api/job/<id>; результат карточками со скачиванием файлов.

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
    """Прогресс джобы: пишем этап в JOBS[job_id]['progress']."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def __call__(self, log_line: str) -> None:
        text = ui.stage_text(log_line)
        if text:
            with JOBS_LOCK:
                if self.job_id in JOBS:
                    JOBS[self.job_id]["progress"] = text


def _worker(job_id: str, mode: str, url: str, brief: str, region: str,
            use_wordstat: bool, combo: bool) -> None:
    job = JOBS[job_id]
    try:
        url = url if url.startswith(("http://", "https://")) else "https://" + url
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
            job["summary"] = ui.seo_html(res)
            job["stats"] = ("групп %d, gap-фраз %d, тем контент-плана %d"
                            % (len(res["core"]), len(res["gaps"]), len(res["plan"])))
            log_run("seo", url, True, 0, 0)
        elif mode == "forecast":
            from app.seo import run_forecast
            res = run_forecast(url, brief, region=region, out_dir=str(OUT_DIR),
                               log=WebProgress(job_id))
            job["files"] = [("forecast.txt", res["txt"], "Медиапрогноз")]
            job["summary"] = ui.forecast_html(res["text"])
            job["stats"] = "прогноз собран из живого Wordstat"
            log_run("forecast", url, True, 0, 0)
        else:
            from app.campaign import generate_campaign
            res = generate_campaign(url, brief, region=region, combo=combo,
                                    out_dir=str(OUT_DIR), log=WebProgress(job_id))
            job["files"] = [
                ("campaign.xlsx", res["xlsx"], "XLSX для Директ Коммандера"),
                ("checklist.txt", res["checklist"], "Чеклист настроек"),
            ]
            job["summary"] = ui.campaign_html(res)
            job["stats"] = "групп %d, фраз %d, ошибок %d" % (
                len(res["campaign"]["groups"]),
                sum(len(g["phrases"]) for g in res["campaign"]["groups"]),
                len(res["report"]["err"]))
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
        JOBS[job_id] = {"status": "running", "progress": "⏳ Запуск...",
                        "files": [], "summary": "", "stats": "", "error": "",
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
              bool(body.get("wordstat")), bool(body.get("combo"))),
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
        "summary": job.get("summary", "") if job["status"] == "done" else "",
        "stats": job.get("stats", "") if job["status"] == "done" else "",
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
<title>Генератор маркетинга на ИИ</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--card2:#1e222b;--text:#e8eaf0;--muted:#9aa1ad;
--accent:#4f8cff;--accent2:#7ee0a3;--border:#2a2f3a;--err:#ff6b6b}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);font:16px/1.5 -apple-system,'Segoe UI',Roboto,Arial,sans-serif;min-height:100vh}
.wrap{max-width:880px;margin:0 auto;padding:28px 20px 60px}
header{display:flex;align-items:center;gap:12px;margin-bottom:26px}
.logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#4f8cff,#7ee0a3);display:flex;align-items:center;justify-content:center;font-size:22px}
h1{font-size:22px;font-weight:700}
.sub{color:var(--muted);font-size:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px}
.modes{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:20px}
.mode{background:var(--card2);border:2px solid var(--border);border-radius:12px;padding:14px;cursor:pointer;text-align:center;transition:.15s}
.mode:hover{border-color:var(--accent)}
.mode.active{border-color:var(--accent);background:rgba(79,140,255,.12)}
.mode .em{font-size:24px}
.mode .t{font-weight:600;margin-top:6px}
.mode .d{font-size:12px;color:var(--muted);margin-top:4px}
label{display:block;font-size:13px;color:var(--muted);margin:14px 0 6px}
input[type=text]{width:100%;padding:13px 14px;background:var(--card2);border:1px solid var(--border);border-radius:10px;color:var(--text);font-size:16px;outline:none}
input[type=text]:focus{border-color:var(--accent)}
.hint{font-size:12px;color:var(--muted);margin-top:5px}
.opts{display:flex;gap:18px;margin:16px 0 6px;flex-wrap:wrap}
.opts label{display:flex;align-items:center;gap:8px;margin:0;color:var(--text);font-size:14px;cursor:pointer}
button{width:100%;margin-top:18px;padding:15px;border:none;border-radius:12px;background:linear-gradient(135deg,#4f8cff,#6db1ff);color:#fff;font-size:17px;font-weight:700;cursor:pointer;transition:.15s}
button:hover{filter:brightness(1.08)}
button:disabled{opacity:.5;cursor:not-allowed}
.progress{display:none;margin-top:18px;padding:16px;background:var(--card2);border-radius:12px;border:1px solid var(--border);font-size:15px}
.bar{height:6px;background:var(--border);border-radius:3px;margin-top:10px;overflow:hidden}
.bar i{display:block;height:100%;width:20%;background:linear-gradient(90deg,#4f8cff,#7ee0a3);border-radius:3px;transition:width .5s}
.result{display:none;margin-top:18px}
.ok{color:var(--accent2);font-weight:700;font-size:17px}
.stats{color:var(--muted);font-size:14px;margin-top:4px}
.summary{margin-top:14px;padding:16px;background:var(--card2);border-radius:12px;font-size:15px;line-height:1.6}
.summary b{color:#fff}
.summary pre{background:var(--bg);padding:10px;border-radius:8px;font-size:12.5px;overflow-x:auto;margin-top:8px}
.files{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin-top:14px}
.file{display:flex;align-items:center;gap:10px;padding:14px;background:var(--card2);border:1px solid var(--border);border-radius:12px;text-decoration:none;color:var(--text);font-weight:600;transition:.15s}
.file:hover{border-color:var(--accent2)}
.file .ic{font-size:22px}
.file .lab{font-size:12.5px;color:var(--muted);font-weight:400;display:block}
.err{display:none;margin-top:18px;padding:16px;background:rgba(255,107,107,.08);border:1px solid var(--err);border-radius:12px;color:var(--err)}
.demo{margin-top:16px;text-align:center}
.demo a{color:var(--accent);font-size:14px;cursor:pointer;text-decoration:none;border-bottom:1px dashed var(--accent)}
footer{margin-top:26px;color:var(--muted);font-size:12.5px;text-align:center}
@media(max-width:640px){.modes{grid-template-columns:1fr}.mode{display:flex;gap:10px;text-align:left;padding:10px 14px}.mode .d{display:none}}
</style>
</head><body><div class="wrap">
<header><div class="logo">🚀</div><div><h1>Генератор маркетинга на ИИ</h1>
<div class="sub">кампания Директа, SEO-отчёт и медиапрогноз из ссылки на сайт</div></div></header>

<div class="card">
<div class="modes">
 <div class="mode active" data-mode="campaign" onclick="setMode(this)">
   <div class="em">🚀</div><div class="t">Кампания Директа</div>
   <div class="d">XLSX для Коммандера + чеклист</div></div>
 <div class="mode" data-mode="seo" onclick="setMode(this)">
   <div class="em">🔍</div><div class="t">SEO-отчёт</div>
   <div class="d">ядро, пробелы, контент-план, meta</div></div>
 <div class="mode" data-mode="forecast" onclick="setMode(this)">
   <div class="em">💰</div><div class="t">Медиапрогноз</div>
   <div class="d">показы, клики, бюджет</div></div>
</div>

<label>Сайт</label>
<input type="text" id="url" placeholder="https://kupppersberg.ru" autocomplete="off">
<div class="hint">например, https://kupppersberg.ru или duplex-shop.ru</div>

<label>Что рекламируем (приоритетная тема, можно пустым)</label>
<input type="text" id="brief" placeholder="встраиваемая техника" autocomplete="off">

<div class="opts">
 <label><input type="checkbox" id="wordstat"> использовать Wordstat API
 <span class="hint">(если задан ключ; основной сценарий работает и без него)</span></label>
</div>

<button id="go" onclick="run()">Собрать ✨</button>
<div class="demo"><a onclick="demo()">🎬 пример: kupppersberg.ru, встраиваемая техника</a></div>
</div>

<div class="progress" id="progress"><span id="ptext">…</span><div class="bar"><i id="pbar"></i></div></div>
<div class="result" id="result">
  <div class="ok" id="okline">Готово</div>
  <div class="stats" id="stats"></div>
  <div class="summary" id="summary"></div>
  <div class="files" id="files"></div>
</div>
<div class="err" id="err"></div>

<footer>Учебный проект НИУ ВШЭ · ИИ в маркетинге · семантика из живого Wordstat · лимиты Директа 1-в-1</footer>
</div>
<script>
let MODE='campaign',KEY=new URLSearchParams(location.search).get('key')||'';
const $=id=>document.getElementById(id);
const KEYQ=KEY?'?key='+KEY:'';
function setMode(el){document.querySelectorAll('.mode').forEach(m=>m.classList.remove('active'));
el.classList.add('active');MODE=el.dataset.mode;}
function demo(){$('url').value='https://kupppersberg.ru';$('brief').value='встраиваемая техника';run();}
async function run(){
 const url=$('url').value.trim();
 if(!url){$('url').focus();return;}
 $('go').disabled=true;$('err').style.display='none';$('result').style.display='none';
 $('progress').style.display='block';$('ptext').textContent='⏳ Запуск...';
 let stage=0;
 const r=await fetch('/api/run'+KEYQ,{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({mode:MODE,url:url,brief:$('brief').value.trim(),
     wordstat:$('wordstat').checked})});
 const j=await r.json();
 if(!r.ok){fail(j.detail||j.error||'ошибка');return;}
 const timer=setInterval(()=>{
   stage=(stage+1)%4;
   fetch('/api/job/'+j.job_id+KEYQ).then(r=>r.json()).then(job=>{
     $('ptext').innerHTML=job.progress||'…';
     $('pbar').style.width=(job.status==='done'?100:20+stage*15)+'%';
     if(job.status==='done'){clearInterval(timer);show(j.job_id);}
     if(job.status==='error'){clearInterval(timer);fail(job.error);}
   }).catch(()=>{});
 },1200);
}
async function show(jobId){
 $('go').disabled=false;$('progress').style.display='none';
 $('result').style.display='block';
 const job=await(await fetch('/api/job/'+jobId+KEYQ)).json();
 $('okline').textContent=MODE==='campaign'?'🚀 Кампания готова':(MODE==='seo'?'🔍 SEO-отчёт готов':'💰 Прогноз готов');
 $('stats').textContent=job.stats;
 $('summary').innerHTML=job.summary;
 const fl=await(await fetch('/api/files/'+jobId+KEYQ)).json();
 $('files').innerHTML=fl.files.map(f=>'<a class="file" href="/files/'+jobId+'/'+f.name+KEYQ+
   '"><span class="ic">'+(f.name.endsWith('.xlsx')?'📊':'📄')+'</span><span>'+f.name+
   '<span class="lab">'+f.label+'</span></span></a>').join('');
}
function fail(msg){$('go').disabled=false;$('progress').style.display='none';
 $('err').style.display='block';$('err').textContent='😔 '+msg;}
</script></body></html>"""


@app.get("/")
async def index(request: Request):
    _check_key(request)
    return HTMLResponse(PAGE)
