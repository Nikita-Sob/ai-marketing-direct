"""Метрики качества генератора: STP, точность/полнота/F1, экономический эффект.

STP (Straight-Through Processing): доля прогонов от URL до готового файла,
прошедших без ручных правок (0 ERR валидатора, без вмешательства человека).
Пишется в output/runs.jsonl, считается по логу.

Точность/полнота/F1: сравнение нашей семантики с эталоном (реальная
кампания Дуплекс Шоп, собранная специалистом). Сравнение по стемам,
совпадением считается вложенность множеств стемов (в обе стороны).

Экономический эффект: охваченный спрос (частоты Wordstat) x прогнозная
модель (CTR, CPC, CR) + экономия ручного труда. Все допущения печатаются.
"""

import json
import re
import time
from typing import Optional
from pathlib import Path

import openpyxl

from app.semantics import STOPWORDS, _stem

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "example_duplex_tgo.xlsx"
RUNS_LOG = Path(__file__).resolve().parent.parent / "output" / "runs.jsonl"

# Экономические допущения (все меняются и печатаются в отчёте)
ECON_ASSUMPTIONS = {
    "hours_manual": 2.5,       # часов ручной сборки кампании специалистом
    "hours_with_bot": 0.15,    # часов с ботом (проверка и импорт)
    "manager_hour_cost": 750.0,  # руб/час, менеджер контекстной рекламы
    "campaigns_per_fte_month": 30,  # кампаний в месяц на одного специалиста
    "dev_cost": 40 * 750.0,    # разработка, часов x руб/час
    "server_month": 1000.0,    # руб/мес сервер
    "wordstat_month": 500.0,   # руб/мес API (опционально)
}

FORECAST_PARAMS = {
    "ctr": 0.07,
    "cpc": 60.0,
    "cr": 0.02,
    "search_share": 0.85,
    "vat": 1.2,
}


# --- сравнение фраз ---

def phrase_stems(phrase: str) -> frozenset:
    """Значимые слова фразы: чистим операторы, стоп-слова, берём стемы."""
    out = set()
    for w in re.findall(r"[a-zа-яё0-9]+", (phrase or "").lower()):
        if w in STOPWORDS:
            continue
        out.add(_stem(w))
    return frozenset(out)


def phrases_match(a: str, b: str) -> bool:
    """Фразы совпали, если стемы одной вложены в другую или пересечение >= 2/3."""
    sa, sb = phrase_stems(a), phrase_stems(b)
    if not sa or not sb:
        return False
    if sa <= sb or sb <= sa:
        return True
    inter = len(sa & sb)
    return inter / min(len(sa), len(sb)) >= 2 / 3


def compare_semantics(generated: list, etalon: list) -> dict:
    """Точность/полнота/F1 наших фраз против эталонных.

    Совпадение many-to-many: фраза считается покрытой, если нашлась
    совпавшая фраза другой стороны (каждая пара используется один раз).
    """
    gen, eta = list(generated), list(etalon)
    used_eta = set()
    matched_gen = 0
    for g in gen:
        for j, e in enumerate(eta):
            if j in used_eta:
                continue
            if phrases_match(g, e):
                used_eta.add(j)
                matched_gen += 1
                break
    matched_eta = matched_gen  # пары одни и те же
    precision = matched_gen / len(gen) if gen else 0.0
    recall = matched_eta / len(eta) if eta else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "gen_total": len(gen), "eta_total": len(eta),
            "matched": matched_gen,
            "unmatched_gen": [g for g in gen if not any(phrases_match(g, e) for e in eta)],
            "unmatched_eta": [e for e in eta if not any(phrases_match(e, g) for g in gen)]}


def etalon_phrases(path: Optional[str] = None) -> list:
    """Фразы реальной кампании из эталонной выгрузки Коммандера (колонка H)."""
    ws = openpyxl.load_workbook(path or TEMPLATE)["Тексты"]
    out = []
    r = 16
    while ws.cell(r, 1).value in ("-", "+"):
        ph = ws.cell(r, 8).value
        if ph and str(ph).strip() and str(ph) != "---autotargeting":
            out.append(" ".join(str(ph).split()))
        r += 1
    return list(dict.fromkeys(out))


def norm_phrase(phrase: str) -> str:
    """Нормализация для сравнения частот: нижний регистр, без операторов."""
    return " ".join(re.findall(r"[a-zа-яё0-9]+", (phrase or "").lower()))


def demand_coverage(generated: list, etalon: list,
                    etalon_freqs: Optional[dict] = None) -> dict:
    """Полнота, взвешенная частотами: какую долю спроса эталона мы покрыли.

    etalon_freqs: {эталонная фраза: частота спроса}. Если нет, взвешиваем
    равномерно (эквивалент обычной полноте).
    """
    covered_n = sum(1 for e in etalon
                    if any(phrases_match(e, g) for g in generated))
    if etalon_freqs:
        total = sum(etalon_freqs.values())
        covered = sum(f for e, f in etalon_freqs.items()
                      if any(phrases_match(e, g) for g in generated))
        return {"coverage": round(covered / total, 3) if total else 0.0,
                "covered_freq": int(covered), "total_freq": int(total),
                "phrases_covered": covered_n, "phrases_total": len(etalon)}
    return {"coverage": round(covered_n / len(etalon), 3) if etalon else 0.0,
            "phrases_covered": covered_n, "phrases_total": len(etalon)}


def economic_effect(coverage: dict,
                      fte_month_campaigns: int = 10) -> dict:
    """Экономический эффект: медиа-эффект покрытия + экономия труда + ROI.

    fte_month_campaigns: сколько кампаний в месяц обрабатывает одно
    рабочее место (для пересчёта месячного эффекта).
    """
    p = FORECAST_PARAMS
    a = ECON_ASSUMPTIONS
    covered = coverage.get("covered_freq", 0)
    shows = covered * p["search_share"]
    clicks = shows * p["ctr"]
    cost = clicks * p["cpc"] * p["vat"]
    conv = clicks * p["cr"]
    media_value = cost  # эквивалент медиабюджета, который генератор покрывает семантикой

    hours_saved = a["hours_manual"] - a["hours_with_bot"]
    labor_per_campaign = hours_saved * a["manager_hour_cost"]
    month_labor = labor_per_campaign * fte_month_campaigns
    month_cost = a["server_month"] + a["wordstat_month"]
    roi = (month_labor - month_cost) / (month_cost + a["dev_cost"] / 12) * 100

    return {
        "media_value_rub": int(media_value),
        "media_clicks": int(clicks),
        "media_conversions": round(conv, 1),
        "hours_saved_per_campaign": round(hours_saved, 2),
        "labor_saving_per_campaign_rub": int(labor_per_campaign),
        "month_labor_saving_rub": int(month_labor),
        "month_cost_rub": int(month_cost),
        "roi_percent": round(roi, 1),
        "fte_now": round(a["campaigns_per_fte_month"] * a["hours_manual"] / 160, 2),
        "fte_bot": round(fte_month_campaigns * a["hours_with_bot"] / 160, 2),
    }


# --- STP ---

def log_run(intent: str, url: str, ok: bool, err_count: int, warn_count: int,
            manual_fixes: int = 0, extra: dict = None) -> None:
    """Записать прогон в лог (для STP и статистики)."""
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "intent": intent, "url": url,
           "ok": ok, "err": err_count, "warn": warn_count, "manual_fixes": manual_fixes}
    if extra:
        rec.update(extra)
    with open(RUNS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def stp_from_log(path: Optional[str] = None) -> dict:
    """STP: доля прогонов без ручных правок (0 ERR, 0 manual_fixes)."""
    p = Path(path or RUNS_LOG)
    if not p.exists():
        return {"total": 0, "stp": None}
    total = clean = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        if r.get("ok") and r.get("err", 1) == 0 and not r.get("manual_fixes"):
            clean += 1
    return {"total": total, "clean": clean,
            "stp": round(clean / total, 3) if total else None}
