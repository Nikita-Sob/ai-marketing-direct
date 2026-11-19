"""Веб-интерфейс генератора (FastAPI).

Дизайн: тёмная премиум-тема (Linear/Vercel), фронт в app/static
(index.html, app.css, app.js, шрифты Inter + JetBrains Mono локально).
Этапы генерации показываются живой лентой по реальным данным джобы.

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
from fastapi.staticfiles import StaticFiles

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
        with JOBS_LOCK:
            if self.job_id in JOBS:
                job = JOBS[self.job_id]
                job.setdefault("log", []).append(
                    [round(time.time() - job["ts"], 2), str(log_line)[:300]])
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


def _card(card: dict) -> dict:
    """Карточка сайта для фронта (без сырого текста страницы)."""
    return {"brand": card.get("brand", ""), "domain": card.get("domain", ""),
            "title": card.get("title", ""), "usps": card.get("usps", [])[:6],
            "categories": [{"name": c.get("name", ""), "url": c.get("url", "")}
                           for c in card.get("categories", [])[:16]]}


def _group(g: dict) -> dict:
    """Группа кампании для фронта: фразы, минус-слова, объявление."""
    ad = g.get("ad") or {}
    return {"name": g.get("base") or g.get("name", ""),
            "phrases": [p for p in g.get("phrases", []) if not p.startswith("---")],
            "minus": g.get("minus_group", []),
            "ad": {"h1": ad.get("h1", ""), "h2": ad.get("h2", ""), "text": ad.get("text", ""),
                   "display_url": ad.get("display_url", ""),
                   "link": ad.get("link_plain", ""),
                   "quick_links": [q[0] for q in ad.get("quick_links", [])][:4],
                   "utochneniya": ad.get("utochneniya", []),
                   "combo_heads": ad.get("combo_heads", []),
                   "combo_texts": ad.get("combo_texts", [])}}


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
                "card": _card(res["card"]),
                "core": [{"name": g["base"], "rows": g["rows"][:12]} for g in res["core"]],
                "gaps": res["gaps"][:20],
                "plan": res["plan"][:10],
                "elapsed": round(time.time() - t0, 1),
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
                "card": _card(res["card"]),
                "groups": res["forecast"]["groups"],
                "total": t,
                "params": {k: v for k, v in res["forecast"]["params"].items()
                           if isinstance(v, (int, float))},
                "elapsed": round(time.time() - t0, 1),
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
                "card": _card(res["card"]),
                "groups": [_group(g) for g in groups],
                "elapsed": round(time.time() - t0, 1),
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
        "log": job.get("log", [])[:300],
        "t": round(time.time() - job.get("ts", time.time()), 2),
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


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index(request: Request):
    _check_key(request)
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache"})
