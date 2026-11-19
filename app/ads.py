"""Генератор объявлений: шаблоны + правила в коде.

Решение от 15.11: тексты собираем из шаблонов и правил, демо не зависит
от внешнего LLM API. Хук зарезервирован (env ADS_LLM_HOOK), в MVP не активен.

На группу: 1 объявление
- h1/h2/text под лимиты 56/30/81 (подсчёт по правилу Коммандера)
- 7 заголовков и 3 текста комбинаторики (строка A="+")
- быстрые ссылки из других категорий (4-8 шт)
- уточнения из УТП карточки

Каждое поле проходит fit_limits, объявление целиком validate_ad.
"""

from app.validator import Ad, validate_ad, is_ok, commander_len, LIMITS
from app.semantics import plus_operators

# UTM-разметка как в эталоне (плейсхолдеры Коммандер подставит сам)
UTM_MAIN = ("?utm_source=yandex&utm_medium=cpc&utm_campaign={campaign_name}"
            "&utm_term={keyword}"
            "&mango=|c:{campaign_id}|g:{gbid}|b:{banner_id}|k:{phrase_id}"
            "|st:{source_type}|a:{addphrases}|s:{source}|t:{position_type}"
            "|p:{position}|r:{retargeting_id}|reg:{region_id}|net:{yad}")


def fit_limits(text: str, limit: int) -> str:
    """Срезать текст до лимита по правилу Коммандера, не рвя слово.

    Финальную точку/восклицание сохраняем: предложение остаётся предложением.
    """
    if commander_len(text) <= limit:
        return text
    words = text.split()
    while words and commander_len(" ".join(words)) > limit:
        words.pop()
    out = " ".join(words).rstrip(",;:")
    if text and text[-1] in ".!?" and not out.endswith((".", "!", "?")):
        out += text[-1]
    return out


def _cap(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:] if s else s


def _plural(base: str) -> bool:
    first = base.split()[0] if base.split() else ""
    return first.endswith(("ы", "и", "а"))


def _link_with_utm(url: str) -> str:
    url = url.rstrip("/")
    if not url:
        url = "https://example.com"
    return url + UTM_MAIN


def generate_group_ad(group: dict, card: dict, idx: int) -> dict:
    """Объявление для группы. idx: номер группы, для чередования шаблонов."""
    base = group["base"]
    cap = _cap(base)
    brand = card.get("brand") or card.get("domain", "")
    usps = list(card.get("usps", []))
    # УТП чередуем между группами: иначе всем группам достаётся одна и та же
    # первая фраза с сайта (наблюдено на СИЗ-ГО: у огнетушителей текст
    # про диэлектрические комплекты)
    if usps:
        k = idx % len(usps)
        usps = usps[k:] + usps[:k]

    # --- заголовки ---
    if _plural(base):
        h1 = fit_limits("Купить %s по низким ценам" % base, LIMITS["h1"])
    else:
        h1 = fit_limits("%s: низкие цены и доставка" % cap, LIMITS["h1"])
    h2s = ["В наличии", "Большой выбор", "Официальный сайт", "Доставка по РФ"]
    h2 = h2s[idx % len(h2s)]

    # --- текст: 1-2 УТП + доставка; предложения обязаны кончаться точкой ---
    def _sentence(s: str) -> str:
        s = (s or "").strip()
        if s and s[-1] not in ".!?":
            s += "."
        return s

    parts = []
    if usps:
        parts.append(fit_limits(_sentence(usps[0]), 70))
    parts.append("Доставка по России.")
    if len(usps) > 1:
        p2 = fit_limits(_sentence(usps[1]), 40)
        if p2 and commander_len(" ".join(parts + [p2])) <= LIMITS["text"]:
            parts.insert(1, p2)
    text = " ".join(parts)
    if not text.endswith((".", "!", "?")):
        text += "."
    text = fit_limits(text, LIMITS["text"])
    if commander_len(text) < 20:
        text = fit_limits("%s: официальный магазин. Доставка по России." % brand,
                          LIMITS["text"])

    # --- 7 заголовков комбинаторики ---
    if _plural(base):
        heads = [
            "Купить %s" % base,
            "%s с доставкой по России" % cap,
            "%s с гарантией" % cap,
            "%s недорого" % cap,
            "%s в наличии" % cap,
            "Большой выбор %s" % base,
            "Официальный сайт %s" % brand,
        ]
    else:
        heads = [
            "%s: низкие цены" % cap,
            "%s с доставкой по России" % cap,
            "%s с гарантией" % cap,
            "%s недорого" % cap,
            "%s в наличии" % cap,
            "Большой выбор: %s" % base,
            "Официальный сайт %s" % brand,
        ]
    combo_heads = []
    for h in heads:
        h = fit_limits(h, LIMITS["h1"])
        if h and h.lower() not in [x.lower() for x in combo_heads]:
            combo_heads.append(h)
    while len(combo_heads) < 7:
        for h in ("%s онлайн", "%s от производителя", "%s быстро" % cap):
            h2_ = fit_limits(h % cap if "%s" in h else h, LIMITS["h1"])
            if h2_ and h2_.lower() not in [x.lower() for x in combo_heads]:
                combo_heads.append(h2_)
            if len(combo_heads) >= 7:
                break
    combo_heads = combo_heads[:7]

    # --- 3 текста комбинаторики ---
    combo_texts = []
    seeds = [
        [usps[0]] if usps else [],
        usps[1:2],
        usps[2:3],
    ]
    for i, seed in enumerate(seeds):
        p = []
        for s in seed:
            p.append(fit_limits(s.rstrip(".") + ".", 60))
        p.append("Доставка по России." if i != 1 else "Гарантия качества.")
        t = fit_limits(" ".join(p), LIMITS["text"])
        if t and t.lower() not in [x.lower() for x in combo_texts]:
            combo_texts.append(t)
    while len(combo_texts) < 3:
        t = fit_limits("%s: большой выбор и доставка по России." % brand, LIMITS["text"])
        if t.lower() not in [x.lower() for x in combo_texts]:
            combo_texts.append(t)
    combo_texts = combo_texts[:3]

    # --- быстрые ссылки: другие категории сайта ---
    quick = []
    own_link = (group.get("category") or {}).get("url", "").rstrip("/")
    own_name = group["base"].lower()
    for c in card.get("categories", []):
        if c["url"].rstrip("/") == own_link or c["name"].lower() == own_name:
            continue
        header = fit_limits(c["name"], LIMITS["quick_header"])
        if not header:
            continue
        desc = fit_limits("%s в наличии и под заказ" % _cap(c["name"]),
                          LIMITS["quick_desc"])
        quick.append((header, desc, _link_with_utm(c["url"])))
        if len(quick) >= 8:
            break
    if len(quick) < 4:
        # добираем служебными страницами до минимума в 4 ссылки
        fallback = [("Доставка", "Доставка по всей России"),
                    ("Гарантия", "Гарантия на всю продукцию"),
                    ("О компании", "Информация о компании"),
                    ("Контакты", "Контакты и обратная связь")]
        for h, d in fallback:
            if len(quick) >= 8:
                break
            if h.lower() not in [q[0].lower() for q in quick]:
                quick.append((h, d, _link_with_utm(card["url"].rstrip("/") + "/")))
        quick = quick[:8]

    # --- уточнения (BN), до 4, каждое <= 25 ---
    utochn = []
    for u in ("Бесплатная доставка", "Гарантия качества", "Оригинальная продукция",
              "Сервис и поддержка", "Доставка по России"):
        if commander_len(u) <= 25 and u not in utochn:
            utochn.append(u)
        if len(utochn) >= 4:
            break

    display_url = fit_limits(card.get("domain", "").replace("www.", "").split(".")[0]
                             .replace("-", " "), LIMITS["display_url"]).replace(" ", "-")

    link = group.get("category", {}).get("url") or card["url"]
    ad = {
        "h1": h1,
        "h2": h2,
        "text": text,
        "combo_heads": combo_heads,
        "combo_texts": combo_texts,
        "quick_links": quick,
        "utochneniya": utochn,
        "link": _link_with_utm(link),
        "link_plain": link.rstrip("/"),
        "display_url": display_url,
    }
    # самопроверка: объявление обязано проходить валидатор
    issues = validate_ad(Ad(h1=h1, h2=h2, text=text, display_url=display_url,
                            quick_links=quick))
    if not is_ok(issues):
        raise ValueError("сгенерировалось объявление с ERR: %s" % issues)
    return ad
