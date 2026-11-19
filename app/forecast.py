"""Медиапрогноз кампании на данных Wordstat.

Модель прозрачная, все допущения печатаются в отчёте:
- показы спроса: частоты Wordstat за 30 дней по региону (реальные данные)
- показы в Директе = спрос x SEARCH_SHARE (доля поиска Яндекса и охват ТГО)
- клики = показы x CTR
- расход = клики x CPC x VAT (НДС 20%)
- конверсии = клики x CR, CPA = расход / конверсии

Дефолты консервативные, их можно заменить реальными цифрами из Директа
(Прогноз бюджета или статистика своего аккаунта).
"""

from app import wordstat

DEFAULTS = {
    "ctr": 0.07,          # прогнозный CTR ТГО на поиске
    "cpc": 60.0,          # средняя цена клика, руб. без НДС
    "cr": 0.02,           # конверсия сайта в обращение
    "search_share": 0.85, # доля спроса, доступная через Директ
    "vat": 1.2,           # НДС 20%
}

# Соответствие имён регионов шаблона Коммандера и ID Wordstat API
REGION_IDS = {
    "россия": "225",
    "москва и область": "213",
    "москва": "213",
    "санкт-петербург": "2",
    "санкт-петербург и область": "2",
}


def region_to_id(region: str) -> str:
    return REGION_IDS.get(region.strip().lower(), wordstat.REGION_RUSSIA)


def forecast_campaign(core: list, params: dict = None) -> dict:
    """Прогноз по семантическому ядру с частотами (seo.build_core).

    Возвращает {"params": {...}, "groups": [{name, shows, clicks, cost,
    conv, cpa}], "total": {...}}.
    """
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (params or {}).items() if v is not None})
    groups, total = [], {"shows": 0, "clicks": 0, "cost": 0, "conv": 0}
    for g in core:
        shows = sum((freq or 0) for _, freq in g["rows"]) * p["search_share"]
        clicks = shows * p["ctr"]
        cost = clicks * p["cpc"] * p["vat"]
        conv = clicks * p["cr"]
        groups.append({
            "name": g["name"],
            "shows": round(shows),
            "clicks": round(clicks),
            "cost": round(cost),
            "conv": round(conv, 1),
            "cpa": round(cost / conv, 1) if conv else 0,
        })
        total["shows"] += shows
        total["clicks"] += clicks
        total["cost"] += cost
        total["conv"] += conv
    total = {"shows": int(round(total["shows"])), "clicks": int(round(total["clicks"])),
             "cost": int(round(total["cost"])), "conv": round(total["conv"], 1)}
    total["cpa"] = round(total["cost"] / total["conv"], 1) if total["conv"] else 0
    return {"params": p, "groups": groups, "total": total}


def render_forecast(fc: dict, url: str, region: str) -> str:
    """Текстовый отчёт прогноза: таблица + допущения."""
    p = fc["params"]
    lines = []
    a = lines.append
    a("МЕДИАПРОГНОЗ КАМПАНИИ")
    a("=" * 56)
    a("Сайт: %s" % url)
    a("Регион: %s (Wordstat ID %s)" % (region, region_to_id(region)))
    a("")
    a("%-22s %10s %9s %11s %8s" % ("Группа", "Показов", "Кликов", "Расход, руб", "CPA"))
    a("-" * 66)
    for g in fc["groups"]:
        a("%-22s %10s %9s %11s %8s" %
          (g["name"][:22], g["shows"], g["clicks"], g["cost"], g["cpa"]))
    t = fc["total"]
    a("-" * 66)
    a("%-22s %10s %9s %11s %8s" % ("ИТОГО", t["shows"], t["clicks"], t["cost"], t["cpa"]))
    a("Конверсий в месяц: %s" % t["conv"])
    a("")
    a("Допущения модели (заменимы на данные из Директа):")
    a("- частоты Wordstat: реальные, 30 дней")
    a("- доля спроса через Директ: %d%%" % round(p["search_share"] * 100))
    a("- CTR на поиске: %s%%" % round(p["ctr"] * 100, 1))
    a("- CPC: %s руб. без НДС, с НДС x%.2f" % (p["cpc"], p["vat"]))
    a("- конверсия сайта: %s%%" % round(p["cr"] * 100, 1))
    return "\n".join(lines)
