"""Семантика: группы ключевых фраз из категорий сайта + Wordstat.

Группа (dict):
- name: короткое имя группы (колонка E)
- base: базовая фраза, например "рации для охоты"
- phrases: ключевые фразы (колонка H), первая = "---autotargeting"
- minus_group: минус-слова на группу (колонка BO)
- category: категория карточки (для ссылки объявления)

Логика:
1. Категории сайта (crawler) -> группы. Бриф уточняет базовую тему.
2. Wordstat GetTop по базе: берём реальные частотные запросы, чистим
   информационный мусор (как выбрать, рейтинг, своими руками...).
3. Если Wordstat недоступен, фразы собираем из шаблонов.
4. Оператор + на стоп-словах (для, в, на, с, по), как в эталоне.
5. Кросс-минусация: в каждой группе минусуем первые слова чужих баз.
"""

import re

from app import wordstat

# Стоп-слова Директа: без + они могут выкинуться из фразы
STOPWORDS = {"для", "в", "и", "на", "с", "по", "от", "к", "у", "об", "о"}

# Информационный мусор: не берём в фразы, уводим в минус кампании
JUNK_WORDS = {
    "как", "какая", "какой", "какую", "каких", "каких", "что", "такое",
    "рейтинг", "обзор", "топ", "своими", "руками", "бесплатно", "скачать",
    "реферат", "курсовая", "форум", "инструкция", "схема", "ремонт",
    "отзывы", "википедия", "вики", "тест", "выбрать",
}

# Минус-фразы на кампанию (строка 9 шапки), формат -!слово
CAMPAIGN_MINUS = [
    "!как", "!какая", "!какой", "!какую", "!что", "!такое", "!рейтинг",
    "!обзор", "!топ", "!своими", "!руками", "!бесплатно", "!скачать",
    "!реферат", "!курсовая", "!форум", "!инструкция", "!ремонт",
    "!отзывы", "!б/у",
]


def normalize_name(name: str) -> str:
    """Имя категории -> базовая фраза: нижний регистр, без мусора."""
    s = name.lower().strip()
    s = re.sub(r"[«»\"'()]+", " ", s)
    s = " ".join(s.split())
    return s


def group_slug(base: str, max_len: int = 20) -> str:
    """Имя группы: слова через _, только буквы/цифры."""
    words = re.findall(r"[a-zа-яё0-9]+", base.lower())
    slug = "_".join(words)[:max_len]
    return slug or "gruppa"


def plus_operators(phrase: str) -> str:
    """Оператор + на стоп-словах, чтобы они учитывались в фразе."""
    toks = []
    for t in phrase.split():
        if t.lower() in STOPWORDS:
            toks.append("+" + t)
        else:
            toks.append(t)
    return " ".join(toks)


def _stem(w: str) -> str:
    """Грубый стем: первые 5 символов (хватает для падежей/чисел)."""
    return w[:5] if len(w) > 5 else w


def _is_junk(phrase: str) -> bool:
    low = phrase.lower()
    return any(re.search(r"\b%s\b" % re.escape(w), low) for w in JUNK_WORDS)


def filter_results(results: list, base: str, max_n: int) -> list:
    """Отфильтровать результаты Wordstat под базу. Возвращает [(фраза с +, частота)].

    Учитывает все слова базы с точностью до словоформы, режет информационный
    мусор. Часть фраз может остаться без частоты (None) для шаблонных фраз.
    """
    base_stems = [_stem(w) for w in re.findall(r"[a-zа-яё0-9]+", base.lower())]
    out = []
    for ph, cnt in results:
        ph = " ".join(ph.split())
        if not ph or _is_junk(ph):
            continue
        stems = [_stem(w) for w in re.findall(r"[a-zа-яё0-9]+", ph.lower())]
        if not all(any(bs == s or s.startswith(bs) or bs.startswith(s)
                       for s in stems) for bs in base_stems):
            continue
        out.append((plus_operators(ph), cnt))
        if len(out) >= max_n:
            break
    return out


def _wordstat_phrases(base: str, max_n: int) -> list:
    """Реальные запросы из Wordstat по базе. Пусто, если API недоступен."""
    try:
        top = wordstat.get_top(base, num_phrases=50)
    except wordstat.WordstatError:
        return []
    return [ph for ph, _ in filter_results(top["results"], base, max_n)]


def _pattern_phrases(base: str, need: int) -> list:
    """Резервные фразы из шаблонов, если Wordstat дал мало."""
    pats = [
        base,
        "купить %s" % base,
        "%s цена" % base,
        "%s недорого" % base,
        "%s интернет магазин" % base,
        "%s с доставкой" % base,
        "лучшие %s" % base,
    ]
    out = []
    for p in pats:
        p = plus_operators(p)
        if p not in out and not _is_junk(p):
            out.append(p)
        if len(out) >= need:
            break
    return out


# Чужие бренды: в кампании/SEO монобрендового сайта им делать нечего
COMPETITOR_BRANDS = (
    "bosch", "siemens", "samsung", "lg", "electrolux", "indesit", "candy",
    "hansa", "midea", "gorenje", "beko", "whirlpool", "zanussi", "aeg",
    "атлант", "atlant", "xiaomi", "redmi", "poco", "dyson", "дайсон",
    "apple", "iphone", "makita", "dewalt", "hytera", "motorola",
    "kenwood", "yaesu", "midland", "turbo", "teXet",
)


def is_monobrand(card: dict) -> bool:
    """Сайт одного бренда: домен совпадает с именем бренда."""
    domain = card.get("domain", "").replace("www.", "").split(".")[0].lower()
    brand = (card.get("brand") or "").lower().replace(" ", "")
    return bool(domain and brand and (domain in brand or brand in domain))


def drop_competitor_brands(rows: list, card: dict) -> list:
    """Для монобрендового сайта убрать фразы с чужими брендами."""
    if not is_monobrand(card):
        return rows
    out = []
    for ph, freq in rows:
        low = " %s " % ph.lower()
        if any(re.search(r"\b%s\b" % re.escape(b), low) for b in COMPETITOR_BRANDS):
            continue
        out.append((ph, freq))
    return out


def build_groups(card: dict, brief: str = "", max_groups: int = 8,
                 max_phrases: int = 7, use_wordstat: bool = True,
                 log=print) -> list:
    """Категории карточки -> группы семантики с фразами и минусами."""
    cats = card.get("categories", [])
    bases = []
    if brief:
        # если бриф задан, он определяет первую (приоритетную) группу
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
        b = normalize_name(card.get("brand", ""))
        bases.append(b or "товары")

    groups = []
    for base in bases:
        phrases = []
        if use_wordstat and wordstat.available():
            phrases = _wordstat_phrases(base, max_phrases)
            if phrases:
                log("  wordstat %s: %d фраз" % (base, len(phrases)))
        if len(phrases) < 4:
            phrases = phrases + [p for p in _pattern_phrases(base, max_phrases)
                                 if p not in phrases]
        phrases = phrases[:max_phrases]
        # для монобрендового сайта чужие бренды в кампанию не берём
        phrases = [ph for ph, _ in drop_competitor_brands([(p, None) for p in phrases], card)]
        # автотаргетинг первой строкой, как в эталоне
        phrases = ["---autotargeting"] + list(dict.fromkeys(phrases))
        groups.append({"name": group_slug(base), "base": base,
                       "phrases": phrases, "minus_group": [], "category": _find_cat(base, cats)})

    # кросс-минусация: минусуем первые слова чужих баз
    for g in groups:
        own = set(re.findall(r"[a-zа-яё0-9]+", g["base"].lower()))
        minus = []
        for other in groups:
            if other is g:
                continue
            first = re.findall(r"[a-zа-яё0-9]+", other["base"].lower())
            if first and first[0] not in own:
                minus.append(first[0])
        g["minus_group"] = ["-%s" % m for m in sorted(set(minus))]
    return groups


def _find_cat(base: str, cats: list) -> dict:
    """Категория, соответствующая базе (для ссылки объявления)."""
    base_words = set(re.findall(r"[a-zа-яё0-9]+", base.lower()))
    best, best_score = None, 0
    for c in cats:
        cwords = set(re.findall(r"[a-zа-яё0-9]+", c["name"].lower()))
        score = len(base_words & cwords)
        if score > best_score:
            best, best_score = c, score
    return best or {}
