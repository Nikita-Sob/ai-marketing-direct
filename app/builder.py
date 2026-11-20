"""Сборка XLSX для Директ Коммандера по эталонному шаблону.

Формат (templates/example_duplex_tgo.xlsx, вкладка "Тексты"):
- шапка кампании в строках 6-13, метки в D, значения в E
- строка заголовков = 14, служебная строка 15 (подписи комбинаторики) не трогаем
- данные с 16-й строки
- формулы длины M/N/O (и Z..AI для комбинаторики) пишем те же, с номером строки
- быстрые ссылки BE/BF/BG: элементы через ||, заголовки в [скобках]
- уточнения BN: через ||
- регион AY: текстовые имена с листа "Регионы" (валидируем)

Новые кампании: колонки ID (D, G, I) оставляем пустыми, Коммандер
назначит свои при загрузке. Это проверяем на дне 5.
"""

import re
import time
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "example_duplex_tgo.xlsx"
HDR_ROW = 14
SERVICE_ROW = 15
DATA_START = 16

# Колонки данных (номера): см. references шаблона
COL = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8, "I": 9,
    "J": 10, "K": 11, "L": 12, "M": 13, "N": 14, "O": 15,
    "P": 16, "Q": 17, "R": 18, "S": 19, "T": 20, "U": 21, "V": 22,
    "W": 23, "X": 24, "Y": 25, "Z": 26, "AA": 27, "AB": 28, "AC": 29,
    "AD": 30, "AE": 31, "AF": 32, "AG": 33, "AH": 34, "AI": 35,
    "AV": 48, "AW": 49, "AX": 50, "AY": 51, "AZ": 52, "BA": 53,
    "BE": 57, "BF": 58, "BG": 59, "BN": 66, "BO": 67,
}


def _len_formula(col_letter: str, row: int) -> str:
    """Формула длины как в эталоне (LEN без ! , . ; : кавычки).

    Аргумент-кавычка экранируется по правилам Excel: четыре кавычки подряд.
    """
    cell = "%s%d" % (col_letter, row)
    chain = cell
    for ch in ('!', ',', '.', ';', ':', '"'):
        arg = '"' * 4 if ch == '"' else '"%s"' % ch
        chain = 'SUBSTITUTE(%s,%s,"")' % (chain, arg)
    return '=IF(%s="","",LEN(%s))' % (cell, chain)


def load_regions(wb) -> set:
    """Текстовые имена регионов с листа "Регионы"."""
    names = set()
    ws = wb["Регионы"]
    for row in ws.iter_rows(values_only=True):
        for v in row:
            if v and str(v).strip() and str(v) != "Регионы":
                names.add(str(v).strip())
    names.add("Россия")
    return names


def validate_region(region: str, regions: set) -> list:
    """Каждое имя в AY должно существовать на листе "Регионы"."""
    issues = []
    for name in [x.strip() for x in region.split(",") if x.strip()]:
        if name not in regions:
            issues.append(name)
    return issues


def _clear_data(ws) -> None:
    """Стереть строки данных эталона (16 и ниже), служебную 15 не трогаем."""
    max_col = ws.max_column
    for r in range(DATA_START, ws.max_row + 1):
        for c in range(1, max_col + 1):
            ws.cell(r, c).value = None


def _clean_minus(words: list) -> list:
    """Убрать минус-фразы с запрещёнными символами (слэш в «б/у» и пр.).

    Директ в минус-фразах разрешает только буквы, цифры, пробел,
    + ! " [ ] и точку. Всё остальное ломает загрузку, поэтому такие
    слова не пишем в файл вовсе.
    """
    from app.validator import validate_minus_words, is_ok
    out = []
    for w in words:
        w = str(w or "").strip()
        if not w:
            continue
        if is_ok(validate_minus_words([w])):
            out.append(w)
    return out


def _fill_header(ws, campaign: dict) -> None:
    """Шапка кампании, строки 6-13: метки в D, значения в E/H."""
    ws.cell(8, 5).value = int(time.strftime("%y%m%d%H%M"))  # № заказа
    minus = _clean_minus(campaign.get("campaign_minus") or [])
    ws.cell(9, 5).value = " ".join("-%s" % m for m in minus) if minus else None
    ws.cell(10, 5).value = 1  # оптимизировать текст под запрос
    ws.cell(11, 5).value = campaign["url"].rstrip("/")
    if campaign.get("phone"):
        ws.cell(13, 5).value = campaign["phone"]
    # r7: тип кампании/места показа/валюта оставляем из шаблона


def _fill_group_rows(ws, r: int, group: dict, ad: dict, region: str,
                     combo: bool = True) -> int:
    """Строки одной группы. Возвращает номер следующей свободной строки.

    combo=True: варианты комбинаторики P..V (7 заголовков) и W..Y
    (3 текста) пишем прямо в строки фраз. Отдельную строку "+" НЕ
    создаём: при импорте новой кампании Коммандер всегда собирает её
    в отдельное объявление (получалась пустая заглушка), а варианты
    из неё вешает на основное объявление группы. combo=False: без
    вариантов, тип Текстово-графическое.
    """
    num = group["num"]
    quick_h = "||".join("[%s]" % h for h, _, _ in ad["quick_links"])
    quick_d = "||".join(d for _, d, _ in ad["quick_links"])
    quick_u = "||".join(u for _, _, u in ad["quick_links"])
    utoch = "||".join(ad["utochneniya"])
    minus_group = " ".join(_clean_minus(group.get("minus_group") or []))
    common = {
        "B": "Комбинаторное" if combo else "Текстово-графическое",
        "C": "-", "E": group["name"], "F": str(num),
        "AV": ad["link"], "AW": ad["display_url"],
        "AY": region, "AZ": "-",
        "BE": quick_h, "BF": quick_d, "BG": quick_u,
        "BN": utoch, "BO": minus_group or None,
    }

    # строки фраз: по одной на фразу, у всех одно объявление;
    # при combo=True варианты комбинаторики лежат прямо в этих строках
    combo_cols = ["P", "Q", "R", "S", "T", "U", "V"]
    combo_formula = ["Z", "AA", "AB", "AC", "AD", "AE", "AF"]
    text_cols = ["W", "X", "Y"]
    text_formula = ["AG", "AH", "AI"]
    for ph in group["phrases"]:
        for col_name, val in common.items():
            ws.cell(r, COL[col_name]).value = val
        ws.cell(r, COL["A"]).value = "-"
        ws.cell(r, COL["H"]).value = ph
        ws.cell(r, COL["J"]).value = ad["h1"]
        ws.cell(r, COL["K"]).value = ad["h2"]
        ws.cell(r, COL["L"]).value = ad["text"]
        ws.cell(r, COL["M"]).value = _len_formula("J", r)
        ws.cell(r, COL["N"]).value = _len_formula("K", r)
        ws.cell(r, COL["O"]).value = _len_formula("L", r)
        if combo:
            for cc, h in zip(combo_cols, ad["combo_heads"]):
                ws.cell(r, COL[cc]).value = h
            for cc, t in zip(text_cols, ad["combo_texts"]):
                ws.cell(r, COL[cc]).value = t
            for fc, cc in zip(combo_formula, combo_cols):
                ws.cell(r, COL[fc]).value = _len_formula(cc, r)
            for fc, cc in zip(text_formula, text_cols):
                ws.cell(r, COL[fc]).value = _len_formula(cc, r)
        r += 1
    return r


def build_xlsx(campaign: dict, out_path: str) -> dict:
    """Сборка файла кампании. campaign: url, region, campaign_minus, groups.

    Каждый элемент groups: num, name, phrases, minus_group, ad (см. ads.py).
    Возвращает {"rows": n, "groups": n, "warnings": [...]}.
    """
    wb = openpyxl.load_workbook(TEMPLATE)
    ws = wb["Тексты"]

    regions = load_regions(wb)
    bad_regions = validate_region(campaign["region"], regions)
    if bad_regions:
        raise ValueError("регионы не найдены на листе Регионы: %s" % bad_regions)

    _clear_data(ws)
    _fill_header(ws, campaign)

    r = DATA_START
    n_phrases = 0
    combo = campaign.get("combo", True)
    for g in campaign["groups"]:
        r = _fill_group_rows(ws, r, g, g["ad"], campaign["region"], combo)
        n_phrases += len(g["phrases"])

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return {"rows": r - DATA_START, "groups": len(campaign["groups"]),
            "phrases": n_phrases}


def validate_built_xlsx(path: str) -> dict:
    """Перечитать готовый файл и проверить все строки валидатором.

    Возвращает {"rows": n, "err": [...], "warn": [...]}.
    """
    from app.validator import Ad, validate_ad, validate_phrase, validate_group, is_ok

    wb = openpyxl.load_workbook(path)
    ws = wb["Тексты"]
    errs, warns, n_ads = [], [], 0
    groups_seen = {}
    r = DATA_START
    while r <= ws.max_row:
        rowtype = ws.cell(r, 1).value
        if rowtype in ("-", "+") and ws.cell(r, COL["E"]).value:
            gname = str(ws.cell(r, COL["E"]).value)
            groups_seen.setdefault(gname, {"phrases": []})
            h1 = str(ws.cell(r, COL["J"]).value or "")
            h2 = str(ws.cell(r, COL["K"]).value or "")
            text = str(ws.cell(r, COL["L"]).value or "")
            ph = str(ws.cell(r, COL["H"]).value or "")
            du = str(ws.cell(r, COL["AW"]).value or "")
            if h1 or text:
                n_ads += 1
                for i in validate_ad(Ad(h1=h1, h2=h2, text=text, display_url=du)):
                    (errs if i.level == "ERR" else warns).append(
                        "r%d %s" % (r, i.message))
            if rowtype == "-" and ph and ph != "---autotargeting":
                groups_seen[gname]["phrases"].append(ph)
            r += 1
        else:
            break
    for gname, gd in groups_seen.items():
        for i in validate_group(gname, gd["phrases"]):
            (errs if i.level == "ERR" else warns).append("%s: %s" % (gname, i.message))
    return {"rows": r - DATA_START, "ads": n_ads, "err": errs, "warn": warns}
