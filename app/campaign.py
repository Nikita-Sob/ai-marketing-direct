"""Полный конвейер: URL + бриф -> XLSX Коммандера + чеклист настроек.

Использование из кода:
    from app.campaign import generate_campaign
    result = generate_campaign("https://duplex-shop.ru", "рации для охоты")
"""

import time
from pathlib import Path

from app import ads, builder, crawler, semantics, wordstat
from app.builder import validate_built_xlsx


def generate_campaign(url: str, brief: str, region: str = "Москва и область",
                      max_groups: int = 8, use_wordstat: bool = True,
                      combo: bool = True, out_dir: str = "output", log=print) -> dict:
    """Собрать кампанию целиком. Возвращает пути и отчёты."""
    t0 = time.time()

    log("1/4 краулер: %s" % url)
    card = crawler.fetch_business_card(url)
    log("   бренд: %s; категорий: %d; УТП: %d" %
        (card["brand"], len(card["categories"]), len(card["usps"])))
    if not card["categories"]:
        log("   WARN: категории не распознаны, группы строим из брифа")

    log("2/4 семантика")
    groups = semantics.build_groups(card, brief=brief, max_groups=max_groups,
                                    use_wordstat=use_wordstat, log=log)
    for g in groups:
        log("   группа %s: %d фраз, минус: %s" %
            (g["name"], len(g["phrases"]), " ".join(g["minus_group"]) or "-"))

    log("3/4 объявления")
    for i, g in enumerate(groups):
        g["num"] = i + 1
        g["ad"] = ads.generate_group_ad(g, card, i)

    # рекомендуемый бюджет: спрос групп из Wordstat x прогнозная модель
    budget_hint = None
    if use_wordstat and wordstat.available():
        demand = 0
        try:
            for g in groups:
                top = wordstat.get_top(g["base"], num_phrases=1)
                demand += top["totalCount"]
            from app.forecast import DEFAULTS
            budget_hint = int(demand * DEFAULTS["search_share"] * DEFAULTS["ctr"]
                               * DEFAULTS["cpc"] * DEFAULTS["vat"])
        except wordstat.WordstatError:
            budget_hint = None

    from app.semantics import CAMPAIGN_MINUS
    campaign = {
        "url": card["url"],
        "region": region,
        "phone": card["phone"],
        "campaign_minus": CAMPAIGN_MINUS,
        "groups": groups,
        "brand": card["brand"],
        "combo": combo,
        "budget_hint": budget_hint,
    }

    log("4/4 сборка XLSX")
    stamp = time.strftime("%Y%m%d_%H%M")
    slug = "".join(ch for ch in card["domain"].split(".")[0] if ch.isalnum())[:20]
    out_dir = Path(out_dir)
    xlsx_path = out_dir / ("%s_%s.xlsx" % (slug, stamp))
    stats = builder.build_xlsx(campaign, str(xlsx_path))

    report = validate_built_xlsx(str(xlsx_path))
    from app.metrics import log_run
    log_run("campaign", card["url"], ok=not report["err"],
            err_count=len(report["err"]), warn_count=len(report["warn"]),
            extra={"groups": stats["groups"], "phrases": stats["phrases"],
                   "xlsx": str(xlsx_path)})
    checklist = build_checklist(campaign, card, stats, report)

    checklist_path = out_dir / ("%s_%s_checklist.txt" % (slug, stamp))
    checklist_path.write_text(checklist, encoding="utf-8")

    log("готово за %.1f c: %s" % (time.time() - t0, xlsx_path))
    return {
        "xlsx": str(xlsx_path),
        "checklist": str(checklist_path),
        "checklist_text": checklist,
        "stats": stats,
        "report": report,
        "card": card,
        "campaign": campaign,
    }


def build_checklist(campaign: dict, card: dict, stats: dict, report: dict) -> str:
    """Чеклист настроек кампании: что проверить руками в Коммандере."""
    lines = []
    a = lines.append
    a("ЧЕКЛИСТ НАСТРОЕК КАМПАНИИ")
    a("=" * 60)
    a("Сайт: %s" % campaign["url"])
    a("Бренд: %s" % campaign.get("brand", ""))
    a("Регион: %s" % campaign["region"])
    a("Групп: %d, фраз: %d (включая автотаргетинг в каждой группе)" %
      (stats["groups"], stats["phrases"]))
    a("")
    a("Сделано генератором:")
    a("- шапка: единая перфоманс-кампания, места показа search, RUB")
    a("- минус-фразы на кампанию: %s" % " ".join("-" + m for m in campaign["campaign_minus"]))
    a("- оптимизация текста под запрос: вкл")
    a("- автоставка: выключена, ставки не заданы")
    a("- каждое объявление комбинаторное: 7 заголовков, 3 текста"
      if campaign.get("combo", True)
      else "- объявления текстово-графические (комбинаторика выключена)")
    a("- быстрые ссылки: 4-8 на группу, уточнения заданы")
    a("- UTM-разметка с плейсхолдерами Коммандера")
    a("")
    a("Проверить руками перед загрузкой/после загрузки:")
    a("1. Загрузить XLSX в Директ Коммандер (Файл -> Загрузить кампанию)")
    a("2. Прогнать модерацию текстов")
    a("3. Задать бюджет и ставки: бюджет в файл загрузчика не входит"
      " (настройка кампании в интерфейсе Директа)")
    if campaign.get("budget_hint"):
        a("   Рекомендуемый бюджет по прогнозу: ~%s руб/мес"
          " (спрос Wordstat x CTR 7%% x CPC 60 руб, с НДС)"
          % ("{:,}".format(campaign["budget_hint"]).replace(",", " ")))
    else:
        a("   Посчитать прогноз: бот, «прогноз: %s | %s»" % (campaign["url"], "тема"))
    a("4. Проверить регионы показа: %s" % campaign["region"])
    a("5. Подключить счётчики Метрики и цели")
    a("6. Организация Яндекс.Справочника: не задана, привязать при наличии")
    if card.get("phone"):
        a("7. Телефон из сайта: %s (проверить корректность)" % card["phone"])
    else:
        a("7. Телефон на сайте не найден, заполнить руками")
    a("")
    a("Валидация файла: строк %d, объявлений %d, ERR %d, WARN %d" %
      (report["rows"], report["ads"], len(report["err"]), len(report["warn"])))
    for e in report["err"]:
        a("  ERR: %s" % e)
    for w in report["warn"][:20]:
        a("  WARN: %s" % w)
    if report["err"]:
        a("")
        a("ВНИМАНИЕ: есть ERR, файл к загрузке НЕ готов.")
    return "\n".join(lines)
