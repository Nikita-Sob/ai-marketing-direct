"""Валидатор объявлений Яндекс Директа (ТГО, поиск).

Главное правило: подсчёт длины 1-в-1 как в Директ Коммандере.
Формулы в колонках M/N/O шаблона (templates/example_duplex_tgo.xlsx)
считают LEN строки после удаления символов: ! , . ; : и кавычка.
Т.е. пунктуация не входит в лимит. Реализация повторяет формулу точно.

Лимиты ТГО (в символах без пунктуации):
- Заголовок 1: 56, обязательный
- Заголовок 2: 30, опциональный
- Текст: 81, обязательный
- Отображаемая ссылка: 20, опциональная
- Заголовки быстрых ссылок: 30 (ссылок от 4 до 8)
- Описания быстрых ссылок: 60

Уровни проблем: ERR = Коммандер/модерация не примет, WARN = риск, решает человек.
"""

from dataclasses import dataclass, field

# Символы, которые Коммандер не считает в длине (из формул шаблона, колонки M/N/O)
PUNCT_IGNORED = "!.,;:\""

LIMITS = {
    "h1": 56,
    "h2": 30,
    "text": 81,
    "display_url": 20,
    "quick_header": 30,
    "quick_desc": 60,
}


def commander_len(s: str) -> int:
    """Длина строки по правилу Коммандера: LEN без символов PUNCT_IGNORED."""
    if not s:
        return 0
    for ch in PUNCT_IGNORED:
        s = s.replace(ch, "")
    return len(s)


@dataclass
class Issue:
    level: str  # "ERR" | "WARN"
    field: str
    message: str


@dataclass
class Ad:
    """Одно объявление. Быстрые ссылки: список (заголовок, описание, адрес)."""
    h1: str = ""
    h2: str = ""
    text: str = ""
    display_url: str = ""
    quick_links: list = field(default_factory=list)


def _check_common(field_name: str, s: str, issues: list) -> None:
    if "\n" in s or "\t" in s:
        issues.append(Issue("ERR", field_name, "перенос строки или таб"))
    if "  " in s:
        issues.append(Issue("WARN", field_name, "двойной пробел"))


def validate_ad(ad: Ad) -> list:
    """Проверка одного объявления. Возвращает список Issue."""
    issues = []

    if not ad.h1.strip():
        issues.append(Issue("ERR", "h1", "заголовок 1 пуст"))
    elif commander_len(ad.h1) > LIMITS["h1"]:
        issues.append(Issue("ERR", "h1", "длина %d > %d" % (commander_len(ad.h1), LIMITS["h1"])))
    _check_common("h1", ad.h1, issues)

    if ad.h2:
        if not ad.h1.strip():
            issues.append(Issue("ERR", "h2", "заголовок 2 без заголовка 1"))
        if commander_len(ad.h2) > LIMITS["h2"]:
            issues.append(Issue("ERR", "h2", "длина %d > %d" % (commander_len(ad.h2), LIMITS["h2"])))
    _check_common("h2", ad.h2, issues)

    if not ad.text.strip():
        issues.append(Issue("ERR", "text", "текст пуст"))
    elif commander_len(ad.text) > LIMITS["text"]:
        issues.append(Issue("ERR", "text", "длина %d > %d" % (commander_len(ad.text), LIMITS["text"])))
    _check_common("text", ad.text, issues)

    if ad.display_url:
        if " " in ad.display_url:
            issues.append(Issue("ERR", "display_url", "пробел в отображаемой ссылке"))
        if ad.display_url.startswith(("http://", "https://")):
            issues.append(Issue("ERR", "display_url", "это отображаемая ссылка, не URL"))
        if commander_len(ad.display_url) > LIMITS["display_url"]:
            issues.append(Issue("ERR", "display_url", "длина %d > %d" % (commander_len(ad.display_url), LIMITS["display_url"])))

    n = len(ad.quick_links)
    if n:
        if n < 4 or n > 8:
            issues.append(Issue("ERR", "quick_links", "быстрых ссылок %d, нужно от 4 до 8" % n))
        for i, (header, desc, url) in enumerate(ad.quick_links, 1):
            if not header.strip():
                issues.append(Issue("ERR", "quick_links", "у ссылки %d пуст заголовок" % i))
            elif commander_len(header) > LIMITS["quick_header"]:
                issues.append(Issue("ERR", "quick_links", "заголовок ссылки %d: длина %d > %d" % (i, commander_len(header), LIMITS["quick_header"])))
            if desc and commander_len(desc) > LIMITS["quick_desc"]:
                issues.append(Issue("ERR", "quick_links", "описание ссылки %d: длина %d > %d" % (i, commander_len(desc), LIMITS["quick_desc"])))
            if not url.strip():
                issues.append(Issue("ERR", "quick_links", "у ссылки %d пуст адрес" % i))
    return issues


def validate_phrase(phrase: str) -> list:
    """Проверка ключевой фразы (колонка H шаблона).

    Правила: минус-слово начинается с дефиса, операторы + и ! клеятся к слову,
    фраза не может состоять только из минус-слов. Регистр Директ приводит
    к нижнему, заглавные буквы без оператора ! теряются, поэтому WARN.
    """
    issues = []
    phrase = (phrase or "").strip()
    if not phrase:
        issues.append(Issue("ERR", "phrase", "фраза пуста"))
        return issues
    if phrase == "---autotargeting":
        return issues
    has_positive = False
    for i, tok in enumerate(phrase.split()):
        if tok.startswith("-"):
            if len(tok) == 1:
                issues.append(Issue("ERR", "phrase", "одиночный дефис в токене %d" % (i + 1)))
            continue
        has_positive = True
        if tok != tok.lower() and not tok.startswith("!"):
            issues.append(Issue("WARN", "phrase", "заглавные без оператора ! в токене %d, Директ приведёт к нижнему регистру" % (i + 1)))
    if not has_positive:
        issues.append(Issue("ERR", "phrase", "фраза состоит только из минус-слов"))
    if "  " in phrase:
        issues.append(Issue("WARN", "phrase", "двойной пробел"))
    return issues


def validate_group(name: str, phrases: list) -> list:
    """Проверка группы: имя, фразы, дубли фраз внутри группы."""
    issues = []
    if not name or not name.strip():
        issues.append(Issue("ERR", "group", "пустое название группы"))
    seen = {}
    for ph in phrases:
        key = (ph or "").strip().lower()
        if key in seen:
            issues.append(Issue("WARN", "group", "дубликат фразы: %s" % ph))
        seen[key] = True
        issues.extend(validate_phrase(ph))
    return issues


def is_ok(issues: list) -> bool:
    """True, если нет ни одной проблемы уровня ERR."""
    return not any(i.level == "ERR" for i in issues)
