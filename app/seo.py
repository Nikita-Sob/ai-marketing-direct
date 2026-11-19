"""SEO-модуль: семантическое ядро, gap-анализ, контент-план, meta-теги.

Работает на том же ядре, что и Директ-генератор: карточка бизнеса (crawler)
+ Wordstat. Выход: XLSX с листами
- «Ядро»: группы, фразы, частоты Wordstat (показов за 30 дней)
- «Gap»: частотные фразы, не закрытые страницами сайта
- «Контент-план»: ТЗ на статьи/страницы под gap
- «Meta»: title и description для существующих категорий

Запуск:
    .venv/bin/python -m app.cli seo https://kuppersberg.ru --brief "техника"
"""

import re
import time
from pathlib import Path

from app import crawler, semantics, wordstat
from app.semantics import (STOPWORDS, filter_results, group_slug,
                           normalize_name, plus_operators)

MAX_PHRASES = 12


def build_core(card: dict, brief: str, max_groups: int = 8,
               use_wordstat: bool = True, region_id: str = wordstat.REGION_RUSSIA,
               log=print) -> list:
    """Семантическое ядро с частотами: [{name, base, rows: [(фраза, частота)]}]."""
    cats = card.get("categories", [])
    bases = []
    if brief:
        b = normalize_name(brief)
        if b:
            bases.append(b)
    for c in cats:
        b = normalize_name(c["name"])
        if b and b not in bases:
            bases.append(b)
        if len(bases) >= max_groups:
            break
    if not bases:
        bases.append(normalize_name(card.get("brand", "")) or "товары")

    core = []
    for base in bases:
        rows = []
        if use_wordstat and wordstat.available():
            try:
                top = wordstat.get_top(base, num_phrases=50, region_id=region_id)
                rows = filter_results(top["results"], base, MAX_PHRASES)
                if rows:
                    log("  wordstat %s: %d фраз, totalCount=%s" %
                        (base, len(rows), top["totalCount"]))
            except wordstat.WordstatError as e:
                log("  wordstat %s недоступен: %s" % (base, e))
        if len(rows) < 4:
            known = {ph for ph, _ in rows}
            for ph in semantics._pattern_phrases(base, MAX_PHRASES):
                if ph not in known:
                    rows.append((ph, None))
                if len(rows) >= MAX_PHRASES:
                    break
        rows = semantics.drop_competitor_brands(rows, card)
        core.append({"name": group_slug(base), "base": base, "rows": rows})
    return core


def _words_stems(s: str) -> set:
    return {semantics._stem(w) for w in re.findall(r"[a-zа-яё0-9]+", s.lower())}


# Транзакционные модификаторы: не требуют отдельной страницы на сайте,
# поэтому не участвуют в gap-анализе
GAP_MODIFIERS = {"купит", "цена", "цены", "недор", "интерн", "магаз",
                 "доставк", "оригин", "лучшие", "лучш", "хорошие", "большой",
                 "москва", "мск", "спб", "ру", "онлайн", "сайт"}


def _phrase_stems(phrase: str) -> set:
    """Значимые слова фразы (без стоп-слов и транзакционных модификаторов)."""
    out = set()
    for w in re.findall(r"[a-zа-яё0-9]+", phrase.lower()):
        if w in STOPWORDS:
            continue
        st = semantics._stem(w)
        if st in GAP_MODIFIERS or w in GAP_MODIFIERS:
            continue
        out.add(st)
    return out


def _stems_covered(phrase_stems: set, cat_stems: set) -> bool:
    """Все слова фразы покрыты категорией, с точностью до словоформы
    (префикс-матчинг, как в filter_results: «шкаф» покрывает «шкафы»)."""
    return all(any(ps == cs or ps.startswith(cs) or cs.startswith(ps)
                   for cs in cat_stems)
               for ps in phrase_stems)


def gap_analysis(core: list, card: dict) -> list:
    """Незакрытые фразы: нет категории, чьё имя/URL покрывает все слова фразы.

    Возвращает [{"phrase", "freq", "group"}], отсортировано по частоте.
    """
    cat_stems = []
    for c in card.get("categories", []):
        cat_stems.append(_words_stems(c["name"]) | _words_stems(c["url"]))
    gaps = []
    for g in core:
        for ph, freq in g["rows"]:
            pst = _phrase_stems(ph)
            if not pst:
                continue
            covered = any(_stems_covered(pst, cs) for cs in cat_stems)
            if not covered:
                gaps.append({"phrase": ph, "freq": freq or 0, "group": g["name"]})
    gaps.sort(key=lambda x: -x["freq"])
    return gaps


def content_plan(gaps: list, core: list, max_items: int = 10) -> list:
    """ТЗ на контент по gap-фразам: кластеризация по главному слову.

    Возвращает [{title, freq, structure: [H2...], format}].
    """
    # главный стем фразы = первый значимый
    clusters = {}
    for g in gaps:
        pst = _phrase_stems(g["phrase"])
        main = g["phrase"].split()[0].lstrip("+!")
        mstem = semantics._stem(main.lower())
        if mstem in STOPWORDS or len(pst) < 1:
            continue
        clusters.setdefault(mstem, []).append(g)
    plan = []
    for mstem, items in sorted(clusters.items(),
                               key=lambda kv: -sum(i["freq"] for i in kv[1])):
        items.sort(key=lambda x: -x["freq"])
        top = items[0]
        freq = sum(i["freq"] for i in items)
        title = top["phrase"].lstrip("+").strip()
        title = title[:1].upper() + title[1:]
        structure = []
        for it in items[1:5]:
            h = it["phrase"].lstrip("+").strip()
            structure.append(h[:1].upper() + h[1:])
        structure.append("Ответы на частые вопросы покупателей")
        plan.append({"title": title, "freq": freq, "structure": structure,
                     "format": "статья в блог" if freq < 3000 else "посадочная категория"})
        if len(plan) >= max_items:
            break
    return plan


def meta_tags(card: dict, core: list) -> list:
    """Title и description для существующих категорий.

    Возвращает [{"page", "url", "title", "description"}].
    """
    brand = card.get("brand") or card.get("domain", "")
    usp = card.get("usps") or [""]
    out = []
    for c in card.get("categories", []):
        name = c["name"].strip()
        title = "%s купить в интернет-магазине %s" % (name, brand)
        if len(title) > 70:
            title = "%s купить в %s" % (name, brand)
        desc = "%s: %s Доставка по России." % (name, usp[0].rstrip("."))
        desc = desc.strip()
        if len(desc) > 160:
            desc = desc[:157].rstrip() + "..."
        out.append({"page": name, "url": c["url"], "title": title[:70],
                    "description": desc[:160]})
    return out


def run_seo(url: str, brief: str, region: str = "Москва и область",
            max_groups: int = 8, use_wordstat: bool = True,
            with_forecast: bool = True, out_dir: str = "output", log=print) -> dict:
    """Полный SEO-отчёт: ядро, gap, контент-план, meta + медиапрогноз."""
    from app import forecast as fc_mod

    t0 = time.time()
    log("1/3 краулер: %s" % url)
    card = crawler.fetch_business_card(url)

    region_id = fc_mod.region_to_id(region)
    log("2/3 семантическое ядро (Wordstat регион %s)" % region_id)
    core = build_core(card, brief, max_groups=max_groups,
                      use_wordstat=use_wordstat, region_id=region_id, log=log)
    total_phrases = sum(len(g["rows"]) for g in core)
    log("   групп: %d, фраз: %d" % (len(core), total_phrases))

    gaps = gap_analysis(core, card)
    log("3/3 gap-анализ: %d незакрытых фраз" % len(gaps))
    plan = content_plan(gaps, core)
    metas = meta_tags(card, core)

    fc = fc_mod.forecast_campaign(core) if with_forecast else None
    fc_text = fc_mod.render_forecast(fc, url, region) if fc else ""

    stamp = time.strftime("%Y%m%d_%H%M")
    slug = "".join(ch for ch in card["domain"].split(".")[0] if ch.isalnum())[:20]
    out_dir = Path(out_dir)
    xlsx_path = out_dir / ("seo_%s_%s.xlsx" % (slug, stamp))
    build_seo_report(card, core, gaps, plan, metas, xlsx_path)

    txt_path = out_dir / ("seo_%s_%s_forecast.txt" % (slug, stamp))
    if fc_text:
        txt_path.write_text(fc_text, encoding="utf-8")

    log("готово за %.1f c: %s" % (time.time() - t0, xlsx_path))
    return {"xlsx": str(xlsx_path), "forecast_txt": str(txt_path) if fc_text else None,
            "forecast_text": fc_text, "core": core, "gaps": gaps,
            "plan": plan, "metas": metas, "card": card, "forecast": fc}


def run_forecast(url: str, brief: str, region: str = "Москва и область",
                 max_groups: int = 8, params: dict = None,
                 out_dir: str = "output", log=print) -> dict:
    """Только медиапрогноз: текст + файл."""
    from app import forecast as fc_mod

    card = crawler.fetch_business_card(url)
    region_id = fc_mod.region_to_id(region)
    core = build_core(card, brief, max_groups=max_groups, use_wordstat=True,
                      region_id=region_id, log=log)
    fc = fc_mod.forecast_campaign(core, params)
    text = fc_mod.render_forecast(fc, url, region)

    stamp = time.strftime("%Y%m%d_%H%M")
    slug = "".join(ch for ch in card["domain"].split(".")[0] if ch.isalnum())[:20]
    out_dir = Path(out_dir)
    txt_path = out_dir / ("forecast_%s_%s.txt" % (slug, stamp))
    txt_path.write_text(text, encoding="utf-8")
    log("прогноз готов: %s" % txt_path)
    return {"txt": str(txt_path), "text": text, "forecast": fc, "card": card}


def build_seo_report(card: dict, core: list, gaps: list, plan: list,
                     metas: list, out_path: str) -> str:
    """Собрать XLSX-отчёт с 4 листами."""
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    bold = Font(bold=True)

    def _sheet(ws, headers, rows):
        ws.append(headers)
        for c in ws[1]:
            c.font = bold
        for r in rows:
            ws.append(r)

    ws = wb.active
    ws.title = "Ядро"
    _sheet(ws, ["Группа", "Фраза", "Показов за 30 дней"],
           [[g["name"], ph, freq] for g in core for ph, freq in g["rows"]])

    _sheet(wb.create_sheet("Gap"), ["Фраза", "Показов за 30 дней", "Группа"],
           [[g["phrase"], g["freq"], g["group"]] for g in gaps])

    plan_rows = [[p["title"], p["freq"], p["format"]]
                 + p["structure"] for p in plan]
    _sheet(wb.create_sheet("Контент-план"),
           ["Тема", "Потенциал, показов/мес", "Формат", "H2-1", "H2-2", "H2-3", "H2-4", "H2-5"],
           plan_rows)

    _sheet(wb.create_sheet("Meta"), ["Страница", "URL", "Title", "Description"],
           [[m["page"], m["url"], m["title"], m["description"]] for m in metas])

    for ws in wb.worksheets:
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(width + 2, 60)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return str(out)
