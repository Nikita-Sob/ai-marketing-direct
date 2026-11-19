"""UI-слой бота: HTML-оформление, клавиатуры, живой прогресс.

Клавиатуры передаём в telebot как готовые dict (inline_keyboard),
как в проверенной схеме food-brain.
"""

import html
import json
import re


def kb(rows):
    """Готовый reply_markup: JSON-строка inline-клавиатуры.

    telebot в свежих версиях не сериализует dict сам (отдаёт его в
    requests как form-data), Telegram отвечает «can't parse reply
    keyboard markup JSON object». Поэтому сериализуем сами.
    """
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)

DEFAULT_REGION = "Москва и область"
REGION_CHOICES = ["Москва и область", "Россия"]


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


# --- клавиатуры (dict, как reply_markup) ---

def main_menu():
    return kb([
        [{"text": "🚀 Кампания Директа", "callback_data": "mode:campaign"},
         {"text": "🔍 SEO-отчёт", "callback_data": "mode:seo"}],
        [{"text": "💰 Медиапрогноз", "callback_data": "mode:forecast"},
         {"text": "ℹ️ Как работает", "callback_data": "about"}],
        [{"text": "🎬 Демо на kuppersberg.ru", "callback_data": "demo"}],
    ])


def cancel_kb():
    return kb([
        [{"text": "✖ Отменить", "callback_data": "cancel"}],
    ])


def skip_kb():
    return kb([
        [{"text": "⏭ Пропустить", "callback_data": "skip"},
         {"text": "✖ Отменить", "callback_data": "cancel"}],
    ])


def region_kb():
    rows = [[{"text": r, "callback_data": "region:%d" % i}]
            for i, r in enumerate(REGION_CHOICES)]
    rows.append([{"text": "✖ Отменить", "callback_data": "cancel"}])
    return kb(rows)


def after_campaign_kb():
    return kb([
        [{"text": "💰 Прогноз по этой же семантике", "callback_data": "again:forecast"},
         {"text": "🔍 SEO-отчёт сайта", "callback_data": "again:seo"}],
        [{"text": "🔁 Ещё кампанию", "callback_data": "again:campaign"},
         {"text": "🏠 В меню", "callback_data": "menu"}],
    ])


def after_seo_kb():
    return kb([
        [{"text": "🚀 Кампания Директа по этому сайту", "callback_data": "again:campaign"}],
        [{"text": "🏠 В меню", "callback_data": "menu"}],
    ])


def after_forecast_kb():
    return kb([
        [{"text": "🚀 Кампания Директа по этому сайту", "callback_data": "again:campaign"},
         {"text": "🔍 SEO-отчёт", "callback_data": "again:seo"}],
        [{"text": "🏠 В меню", "callback_data": "menu"}],
    ])


def error_kb():
    return kb([
        [{"text": "🔄 Попробовать снова", "callback_data": "again:last"},
         {"text": "🏠 В меню", "callback_data": "menu"}],
    ])


# --- тексты ---

WELCOME = (
    "Привет! Я <b>генератор маркетинга на ИИ</b>.\n"
    "Учебный проект НИУ ВШЭ, курс «ИИ в маркетинге и коммуникациях».\n\n"
    "Дай ссылку на сайт, я соберу:\n"
    "🚀 <b>кампанию Яндекс Директа</b> (ТГО) — XLSX для Коммандера\n"
    "🔍 <b>SEO-отчёт</b> — ядро, пробелы, контент-план, meta-теги\n"
    "💰 <b>медиапрогноз</b> — показы, клики, бюджет\n\n"
    "Выбирай кнопкой или пришли одной строкой:\n"
    "<code>кампания: https://kuppersberg.ru | встраиваемая техника</code>"
)

ABOUT = (
    "ℹ️ <b>Как я работаю</b>\n\n"
    "1. Обхожу сайт: категории, УТП, контакты\n"
    "2. Собираю семантику из живого Wordstat (Яндекс Search API)\n"
    "3. Пишу тексты по правилам Директа: лимиты 56/30/81,\n"
    "   подсчёт длины 1-в-1 как в Коммандере\n"
    "4. Проверяю каждую строку валидатором и собираю XLSX\n\n"
    "Вся генерация на сервере, занимает 10-30 секунд.\n"
    "Комбинаторика включена по умолчанию: каждому объявлению\n"
    "7 заголовков и 3 текста. Слова «без комбо» отключают.\n"
    "Скорость: кампания ~10 с, SEO-отчёт ~5 с."
)


# --- живой прогресс ---

STAGE_PATTERNS = [
    (re.compile(r"1/4 краулер|1/3 краулер"), "🌐 <b>1/4</b> Обхожу сайт..."),
    (re.compile(r"2/4 семантика|2/3 семантическое"), "🔑 <b>2/4</b> Семантика из Wordstat..."),
    (re.compile(r"3/4 объявления"), "✍️ <b>3/4</b> Пишу объявления..."),
    (re.compile(r"4/4 сборка"), "📦 <b>4/4</b> Собираю XLSX..."),
    (re.compile(r"3/3 gap"), "🔎 <b>3/3</b> Ищу незакрытые запросы..."),
    (re.compile(r"wordstat"), None),  # шум про частоты не показываем
]


def stage_text(log_line: str) -> str:
    """Строка лога генератора -> текст этапа для прогресс-сообщения."""
    for pat, text in STAGE_PATTERNS:
        if pat.search(log_line):
            return text
    return None


# --- сводки результатов (HTML) ---

def fmt_num(n) -> str:
    return "{:,}".format(int(n)).replace(",", " ")


def campaign_html(res: dict) -> str:
    c = res["campaign"]
    rep = res["report"]
    lines = [
        "🚀 <b>Кампания готова</b>",
        "",
        "🌐 %s" % esc(c["url"]),
        "📍 %s" % esc(c["region"]),
        "",
        "<b>Групп: %d, фраз: %d</b> (автотаргетинг в каждой)" % (
            len(c["groups"]), sum(len(g["phrases"]) for g in c["groups"])),
        "",
    ]
    for g in c["groups"][:6]:
        lines.append("• <b>%s</b> — %d фраз" % (esc(g["name"]), len(g["phrases"])))
    if len(c["groups"]) > 6:
        lines.append("... и ещё %d" % (len(c["groups"]) - 6))
    lines += [
        "",
        "✅ Проверка: %d строк, ошибок %d, предупреждений %d" % (
            rep["rows"], len(rep["err"]), len(rep["warn"])),
    ]
    return "\n".join(lines)


def seo_html(res: dict) -> str:
    lines = [
        "🔍 <b>SEO-отчёт готов</b>",
        "",
        "🌐 %s" % esc(res["card"]["url"]),
        "",
        "🔑 Ядро: <b>%d фраз</b> с частотами" % sum(len(g["rows"]) for g in res["core"]),
        "🔎 Незакрытых запросов: <b>%d</b>" % len(res["gaps"]),
        "📝 Тем для контент-плана: <b>%d</b>" % len(res["plan"]),
        "🏷 Meta-теги для %d категорий" % len(res["metas"]),
        "",
        "<b>Топ-3 темы контент-плана:</b>",
    ]
    for p in res["plan"][:3]:
        lines.append("• %s <i>(%s показов/мес)</i>" % (esc(p["title"]), fmt_num(p["freq"])))
    return "\n".join(lines)


def forecast_html(text: str) -> str:
    """Прогноз уже отформатирован таблицей, оборачиваем в моноширинный блок."""
    # вырезаем блок с таблицей
    table = []
    keep = False
    for line in text.splitlines():
        if line.startswith(("Группа", "----")) or (keep and line.strip()):
            keep = True
            table.append(line)
            if line.startswith("Конверсий"):
                break
        elif line.startswith("ИТОГО"):
            table.append(line)
    if table:
        return "💰 <b>Медиапрогноз</b>\n\n<pre>%s</pre>" % esc("\n".join(table))
    return "💰 <b>Медиапрогноз</b>\n\n%s" % esc(text[:3500])
