"""Краулер: главная страница сайта -> карточка бизнеса.

Карточка (dict):
- url, domain: сайт
- brand: имя бренда/магазина из title
- title, description: мета-данные
- categories: [{"name", "url"}] разделы каталога
- usps: короткие фразы про гарантию/доставку/сервис (для текстов объявлений)
- phone: телефон, если нашли

Обход лёгкий: только главная страница, без JS. Сайты с ddos-guard
открываются при обычном User-Agent браузера (проверено на duplex-shop.ru).
"""

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Служебные пункты меню, не категории
SERVICE_WORDS = {
    "доставка", "оплата", "доставка и оплата", "оплата и доставка", "контакты",
    "о нас", "о компании", "о магазине", "корзина", "вход", "регистрация",
    "личный кабинет", "отзывы", "акции", "новости", "блог", "статьи",
    "гарант", "гарантия", "возврат", "сервис", "faq", "вопросы", "избранное",
    "сравнение", "вакансии", "оптом", "помощь", "поддержка", "политика",
    "каталог", "перейти в каталог", "гарантия и возврат", "сравнить",
}

CAT_PATH_KEYWORDS = ("catalog", "category", "shop", "goods", "kategor", "cat/")

# Сегменты пути, где не бывает категорий: товары, бренды, услуги, служебное
BAD_PATH_SEGMENTS = ("product", "brand", "brands", "services", "cart", "favorite",
                     "compare", "sravnit", "account", "login", "auth", "checkout",
                     "search", "privacy", "usloviya", "news", "blog", "sale")

# Слова в тексте ссылки, по которым понимаем, что это не категория
BAD_NAME_WORDS = ("риски", "серого", "импорта", "политик", "персональн",
                 "обработки", "профиль", "сертификаты", "клиентам", "оптом",
                 "реквизиты", "войти", "регистрац", "подробнее", "о магазине",
                 "обои", "условия", "справка", "вопрос", "ответ", "договор",
                 "оферта", "правил")

USP_KEYS = ("гарантия", "гаранти", "доставка", "оригинал", "производит",
            "сервис", "установ", "склад", "возврат", "настро", "запрограммир")

_PHONE_RE = re.compile(r"(?:\+7|8)[\s(-]?\d{3}[\s)-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}")

_COUNTER_RE = re.compile(r"\s+\d{1,6}$")


class CrawlError(Exception):
    pass


def _get(url: str, timeout: int = 25) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
                         timeout=timeout)
    except requests.RequestException as e:
        raise CrawlError("не открылся %s: %s" % (url, str(e)[:150]))
    if r.status_code != 200:
        raise CrawlError("HTTP %s на %s" % (r.status_code, url))
    # кодировка: если сервер не сказал или соврал (частый случай у сайтов
    # на windows-1251), определяем по байтам, иначе получаем кракозябры
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _clean(s: str) -> str:
    return " ".join((s or "").split())


def _same_site(base_domain: str, url: str) -> bool:
    host = urlparse(url).netloc.lower().replace("www.", "")
    base = base_domain.replace("www.", "")
    return host == base or host.endswith("." + base)


def _brand_from_title(title: str, domain: str) -> str:
    if title:
        first = re.split(r"[–—|«»]|\s-\s", title, maxsplit=1)[0]
        first = _clean(first.rstrip(" -–—|"))
        if first and len(first) <= 30:
            return first
    return domain.replace("www.", "").split(".")[0]


def _categories(soup, base_url: str, domain: str) -> list:
    """Категории: внутренние ссылки с коротким осмысленным текстом.

    Оценка: путь с catalog/category/shop выше, плюс частота повторения
    ссылки на странице. Служебные пункты отбрасываем.
    """
    cand = {}
    for a in soup.find_all("a", href=True):
        text = _clean(a.get_text(" ", strip=True))
        text = _COUNTER_RE.sub("", text)  # счётчик товаров в пункте меню
        if not (3 <= len(text) <= 40):
            continue
        low_text = text.lower()
        if low_text.rstrip("…") in SERVICE_WORDS:
            continue
        if any(w in low_text for w in BAD_NAME_WORDS):
            continue
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        full = urljoin(base_url, href)
        if not _same_site(domain, full):
            continue
        path = urlparse(full).path.strip("/")
        if not path:
            continue
        segs = [s for s in path.split("/") if s]
        if not (1 <= len(segs) <= 5):
            continue
        if any(any(bad == seg or seg.startswith(bad) for bad in BAD_PATH_SEGMENTS)
               for seg in segs):
            continue
        score = 0
        low = path.lower()
        if any(k in low for k in CAT_PATH_KEYWORDS):
            score += 3
        if 2 <= len(segs) <= 4:
            score += 1
        key = path.lower()
        c = cand.setdefault(key, {"text": text, "url": full, "score": 0, "n": 0})
        c["score"] = max(c["score"], score)
        c["n"] += 1
        if 3 <= len(text) < len(c["text"]):
            c["text"] = text

    ranked = sorted(cand.values(), key=lambda c: (c["score"], c["n"]), reverse=True)
    out, seen_texts = [], set()
    for c in ranked:
        t = c["text"]
        if t.lower() in seen_texts:
            continue
        seen_texts.add(t.lower())
        out.append({"name": t, "url": c["url"]})
        if len(out) >= 15:
            break
    return out


def _usps(soup, description: str) -> list:
    """Короткие фразы с УТП из мета-описания и текста страницы."""
    pool = []
    if description:
        pool.append(description)
    for tag in soup.find_all(["h1", "h2", "h3", "li", "p", "div"]):
        t = _clean(tag.get_text(" ", strip=True))
        if not t or len(t) > 90:
            continue
        pool.append(t)
    out, seen = [], set()
    for t in pool:
        # разделители предложений и маркетинговые значки
        for part in re.split(r"(?<=[.!?])\s+|[|•·✅]", t):
            part = _clean(part)
            if not (25 <= len(part) <= 85):
                continue
            low = part.lower()
            if not any(k in low for k in USP_KEYS):
                continue
            key = low.rstrip(".")
            if key in seen:
                continue
            seen.add(key)
            out.append(part)
            if len(out) >= 8:
                return out
    return out


def fetch_business_card(url: str) -> dict:
    """Главная страница -> карточка бизнеса."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(url).netloc.lower()

    title = _clean(soup.title.get_text()) if soup.title else ""
    desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta:
        desc = _clean(meta.get("content", ""))

    phone = ""
    m = _PHONE_RE.search(soup.get_text(" ", strip=True))
    if m:
        phone = m.group(0).strip()

    return {
        "url": url,
        "domain": domain.replace("www.", ""),
        "brand": _brand_from_title(title, domain),
        "title": title,
        "description": desc,
        "categories": _categories(soup, url, domain),
        "usps": _usps(soup, desc),
        "phone": phone,
        "text_sample": soup.get_text(" ", strip=True)[:2000],
    }
