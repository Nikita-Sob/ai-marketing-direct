"""Telegram-бот генератора маркетинга (ВШЭ, ИИ в маркетинге).

UX: меню на инлайн-кнопках, пошаговый диалог (сайт -> бриф -> регион),
живой прогресс с редактированием сообщения, кросс-действия после
результата (прогноз/SEO по той же семантике), быстрая однострочная
запись сохранена: "кампания: URL | бриф | регион".

Токен в env HSE_BOT_TOKEN (/root/.hermes/.env). Запуск:
.venv/bin/python -m app.bot. Прод: systemd hse-direct-bot.service.
"""

import os
import threading
import traceback
from pathlib import Path

import telebot

from app import ui

ENV_PATH = "/root/.hermes/.env"

BOT_COMMANDS = [
    ("start", "Главное меню"),
    ("campaign", "Кампания Директа: /campaign URL | бриф"),
    ("seo", "SEO-отчёт: /seo URL | тема"),
    ("forecast", "Медиапрогноз: /forecast URL | тема"),
    ("status", "Статус бота"),
    ("help", "Как работает"),
]

DEMO_URL = "https://kuppersberg.ru"
DEMO_BRIEF = "встраиваемая техника"


def load_env(path: str = ENV_PATH) -> None:
    """Подтянуть секреты из .hermes/.env, не перетирая уже заданные."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# --- парсинг (чистые функции, покрыты тестами) ---

def parse_intent(text: str) -> str:
    """"campaign" | "seo" | "forecast" по первому слову сообщения."""
    low = (text or "").strip().lower()
    for key in ("seo", "сео"):
        if low.startswith(key):
            return "seo"
    for key in ("прогноз", "forecast", "медиапрогноз"):
        if low.startswith(key):
            return "forecast"
    return "campaign"


def parse_request(text: str, intent: str = None) -> dict:
    """Сообщение -> {"url", "brief", "region", "combo", "max_groups"}.

    Кидает ValueError, если URL не распознан.
    """
    t = " ".join((text or "").split())
    intent = intent or parse_intent(t)
    low = t.lower()
    combo = "комбо" in low or "combo" in low
    if low.startswith(("seo", "сео", "прогноз", "forecast", "медиапрогноз",
                       "кампания", "campaign")):
        # срезаем слово-интент и двоеточие
        if ":" in t[:14] and not t.startswith(("http://", "https://")):
            t = t.split(":", 1)[1].strip()
        else:
            parts0 = t.split(None, 1)
            t = parts0[1].strip() if len(parts0) > 1 else ""
    parts = [p.strip() for p in t.split("|") if p.strip()]
    if not parts:
        raise ValueError("пусто")
    url = parts[0]
    if "." not in url or " " in url:
        raise ValueError("не понял сайт: %r" % url[:50])
    brief = parts[1] if len(parts) > 1 else ""
    region = parts[2] if len(parts) > 2 else ui.DEFAULT_REGION
    return {"url": url, "brief": brief, "region": region,
            "combo": combo, "max_groups": 6}


def _is_url(text: str) -> bool:
    t = (text or "").strip()
    return "." in t and " " not in t and not t.startswith("/")


# --- состояния диалогов ---

class Chats:
    """In-memory состояния: шаг диалога, черновик запроса, последняя работа."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {}    # chat_id -> {"step", "intent", "req": {...}}
        self.last = {}     # chat_id -> {"req", "intent"}
        self.running = set()

    def begin(self, chat_id: int, intent: str) -> None:
        with self.lock:
            self.state[chat_id] = {"step": "url", "intent": intent,
                                   "req": {"url": "", "brief": "", "region": "",
                                           "combo": False, "max_groups": 6}}

    def set_url(self, chat_id: int, url: str) -> None:
        with self.lock:
            self.state[chat_id]["req"]["url"] = url
            self.state[chat_id]["step"] = "brief"

    def set_brief(self, chat_id: int, brief: str) -> None:
        with self.lock:
            self.state[chat_id]["req"]["brief"] = brief
            self.state[chat_id]["step"] = "region"

    def set_region(self, chat_id: int, region: str) -> None:
        with self.lock:
            self.state[chat_id]["req"]["region"] = region
            self.state[chat_id]["step"] = None

    def cancel(self, chat_id: int) -> None:
        with self.lock:
            self.state.pop(chat_id, None)

    def get(self, chat_id: int):
        with self.lock:
            return dict(self.state.get(chat_id, {}))

    def remember(self, chat_id: int, intent: str, req: dict) -> None:
        with self.lock:
            self.last[chat_id] = {"intent": intent, "req": dict(req)}

    def last_of(self, chat_id: int):
        with self.lock:
            return dict(self.last.get(chat_id, {}))

    def try_run(self, chat_id: int) -> bool:
        with self.lock:
            if chat_id in self.running:
                return False
            self.running.add(chat_id)
            return True

    def done(self, chat_id: int) -> None:
        with self.lock:
            self.running.discard(chat_id)


# --- генерация с живым прогрессом ---

class Progress:
    """Редактирует сообщение прогресса по логам генератора."""

    def __init__(self, bot, chat_id: int):
        self.bot = bot
        self.chat_id = chat_id
        self.msg_id = None

    def __call__(self, log_line: str) -> None:
        text = ui.stage_text(log_line)
        if not text:
            return
        try:
            if self.msg_id is None:
                msg = self.bot.send_message(self.chat_id, "⏳ " + text,
                                            parse_mode="HTML")
                self.msg_id = msg.message_id
            else:
                self.bot.edit_message_text("⏳ " + text, self.chat_id,
                                          self.msg_id, parse_mode="HTML")
        except Exception:
            pass


def _send_doc(bot, chat_id, path: str, visible_name: str, caption: str = ""):
    with open(path, "rb") as f:
        bot.send_document(chat_id, f, visible_file_name=visible_name,
                          caption=caption or None, parse_mode="HTML")


def _run_job(bot, chat_id: int, intent: str, req: dict, chats: Chats) -> None:
    """Генерация в отдельном потоке: прогресс, файлы, сводка, кнопки."""
    try:
        bot.send_chat_action(chat_id, "typing")
        progress = Progress(bot, chat_id)
        url = req["url"] if req["url"].startswith(("http://", "https://")) \
            else "https://" + req["url"]
        req = dict(req, url=url)
        chats.remember(chat_id, intent, req)  # для кнопок «ещё раз» и после ошибок

        if intent == "seo":
            from app.seo import run_seo
            res = run_seo(req["url"], req["brief"], region=req["region"],
                          max_groups=req["max_groups"], out_dir="output",
                          log=progress)
            bot.send_chat_action(chat_id, "upload_document")
            slug = Path(res["xlsx"]).stem.split("_")[1]
            _send_doc(bot, chat_id, res["xlsx"], "seo_%s.xlsx" % slug,
                      "🔍 SEO-отчёт: ядро, gap, контент-план, meta")
            if res["forecast_txt"]:
                _send_doc(bot, chat_id, res["forecast_txt"],
                          "forecast_%s.txt" % slug, "💰 Медиапрогноз")
            bot.send_message(chat_id, ui.seo_html(res), parse_mode="HTML",
                            reply_markup=ui.after_seo_kb())
        elif intent == "forecast":
            from app.seo import run_forecast
            res = run_forecast(req["url"], req["brief"], region=req["region"],
                               max_groups=req["max_groups"], out_dir="output",
                               log=progress)
            slug = Path(res["txt"]).stem.split("_")[1]
            bot.send_message(chat_id, ui.forecast_html(res["text"]),
                             parse_mode="HTML", reply_markup=ui.after_forecast_kb())
            _send_doc(bot, chat_id, res["txt"], "forecast_%s.txt" % slug)
        else:
            from app.campaign import generate_campaign
            res = generate_campaign(req["url"], req["brief"], region=req["region"],
                                    max_groups=req["max_groups"], combo=req["combo"],
                                    out_dir="output", log=progress)
            bot.send_chat_action(chat_id, "upload_document")
            slug = Path(res["xlsx"]).stem.split("_")[0]
            _send_doc(bot, chat_id, res["xlsx"], "campaign_%s.xlsx" % slug,
                      "🚀 XLSX для Директ Коммандера")
            _send_doc(bot, chat_id, res["checklist"],
                      "checklist_%s.txt" % slug, "📋 Чеклист настроек кампании")
            bot.send_message(chat_id, ui.campaign_html(res), parse_mode="HTML",
                            reply_markup=ui.after_campaign_kb())
    except Exception as e:  # pragma: no cover
        traceback.print_exc()
        try:
            bot.send_message(
                chat_id,
                "😔 Не получилось: <i>%s</i>\n\nПроверь ссылку и попробуй ещё раз."
                % ui.esc(str(e)[:200]),
                parse_mode="HTML", reply_markup=ui.error_kb())
        except Exception:
            pass
    finally:
        chats.done(chat_id)


# --- сам бот ---

def main() -> None:
    load_env()
    token = os.environ.get("HSE_BOT_TOKEN")
    if not token:
        raise SystemExit("нет HSE_BOT_TOKEN в env")
    allowed_raw = os.environ.get("HSE_BOT_ALLOWED_USERS", "")
    allowed = {x for x in allowed_raw.replace(",", " ").split() if x}

    bot = telebot.TeleBot(token)
    try:
        bot.set_my_commands([telebot.types.BotCommand(c, d) for c, d in BOT_COMMANDS])
    except Exception:
        pass
    chats = Chats()
    print("бот запущен (UX v2), long polling; allowlist:", sorted(allowed) or "все")

    def _check_user(m):
        if allowed and str(m.from_user.id) not in allowed:
            bot.reply_to(m, "Доступ закрыт.")
            return False
        return True

    def _start_job(m, intent, req):
        if not chats.try_run(m.chat.id):
            bot.reply_to(m, "⏳ Уже собираю, дай мне закончить.")
            return
        threading.Thread(target=_run_job,
                         args=(bot, m.chat.id, intent, req, chats),
                         daemon=True).start()

    def _ask_url(m, intent):
        chats.begin(m.chat.id, intent)
        label = {"campaign": "кампанию Директа", "seo": "SEO-отчёт",
                 "forecast": "медиапрогноз"}[intent]
        bot.send_message(m.chat.id,
                        "🌐 Пришли ссылку на сайт.\n"
                        "Например: <code>https://kuppersberg.ru</code>\n\n"
                        "Собираю: <b>%s</b>" % label,
                        parse_mode="HTML", reply_markup=ui.cancel_kb())

    @bot.message_handler(commands=["start", "menu"])
    def _start(m):
        if not _check_user(m):
            return
        bot.send_message(m.chat.id, ui.WELCOME, parse_mode="HTML",
                         reply_markup=ui.main_menu(), disable_web_page_preview=True)

    @bot.message_handler(commands=["help"])
    def _help(m):
        bot.send_message(m.chat.id, ui.ABOUT, parse_mode="HTML",
                        reply_markup=ui.main_menu())

    @bot.message_handler(commands=["status"])
    def _status(m):
        from app import wordstat
        ws = "✅ подключён" if wordstat.available() else "⚠️ недоступен (шаблонные фразы)"
        bot.send_message(m.chat.id,
                        "🤖 Бот работает\n📊 Wordstat: %s\n🕒 Аптайм процесса: %s" % (
                            ws, _uptime()), parse_mode="HTML")

    @bot.message_handler(commands=["campaign", "seo", "forecast"])
    def _cmd_mode(m):
        if not _check_user(m):
            return
        _ask_url(m, parse_intent(m.text.split()[0][1:]))

    @bot.callback_query_handler(func=lambda c: True)
    def _callback(c):
        data = c.data or ""
        chat_id = c.message.chat.id
        try:
            if data == "cancel":
                chats.cancel(chat_id)
                bot.edit_message_text("Отменено. /start — меню.", chat_id,
                                      c.message.message_id)
            elif data == "menu":
                bot.edit_message_text(ui.WELCOME, chat_id, c.message.message_id,
                                      parse_mode="HTML", reply_markup=ui.main_menu())
            elif data == "about":
                bot.edit_message_text(ui.ABOUT, chat_id, c.message.message_id,
                                      parse_mode="HTML", reply_markup=ui.main_menu())
            elif data == "demo":
                _start_job(c.message, "campaign",
                           {"url": DEMO_URL, "brief": DEMO_BRIEF,
                            "region": ui.DEFAULT_REGION, "combo": False,
                            "max_groups": 6})
            elif data.startswith("mode:"):
                _ask_url(c.message, data.split(":", 1)[1])
            elif data.startswith("region:"):
                st = chats.get(chat_id)
                if st:
                    region = ui.REGION_CHOICES[int(data.split(":")[1])]
                    chats.set_region(chat_id, region)
                    _start_job(c.message, st["intent"],
                               dict(st["req"], region=region))
            elif data.startswith("again:"):
                last = chats.last_of(chat_id)
                what = data.split(":", 1)[1]
                if what == "last" and last:
                    what = last["intent"]
                if last and what in ("campaign", "seo", "forecast"):
                    _start_job(c.message, what, last["req"])
                else:
                    bot.send_message(chat_id, "Подходящих данных нет, начни заново: /start")
            elif data == "skip":
                st = chats.get(chat_id)
                if st and st["step"] == "brief":
                    chats.set_brief(chat_id, "")
                    bot.send_message(chat_id,
                                    "📍 Регион показа?\n"
                                    "Или напиши свой, как на листе «Регионы» в Коммандере.",
                                    reply_markup=ui.region_kb())
            bot.answer_callback_query(c.id)
        except Exception:
            traceback.print_exc()
            try:
                bot.answer_callback_query(c.id, "Ошибка, попробуй /start")
            except Exception:
                pass

    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def _on_text(m):
        if not _check_user(m):
            return
        st = chats.get(m.chat.id)

        # 1) активный диалог: сайт -> бриф
        if st and st.get("step") == "url":
            if _is_url(m.text):
                chats.set_url(m.chat.id, m.text.strip())
                bot.reply_to(m, "🎯 Что рекламируем? Одной фразой.\n"
                               "Это приоритетная тема, остальное соберу сам.",
                            reply_markup=ui.skip_kb())
            else:
                bot.reply_to(m, "Не похоже на ссылку. Пришли вида "
                               "<code>https://kuppersberg.ru</code>",
                            parse_mode="HTML", reply_markup=ui.cancel_kb())
            return
        if st and st.get("step") == "brief":
            chats.set_brief(m.chat.id, m.text.strip())
            bot.reply_to(m, "📍 Регион показа?\n"
                           "Или напиши свой, как на листе «Регионы» в Коммандере.",
                        reply_markup=ui.region_kb())
            return
        if st and st.get("step") == "region":
            chats.set_region(m.chat.id, m.text.strip())
            s2 = chats.get(m.chat.id)
            _start_job(m, s2["intent"], s2["req"])
            return

        # 2) быстрая запись одной строкой
        try:
            req = parse_request(m.text)
            intent = parse_intent(m.text)
            label = {"seo": "SEO-отчёт", "forecast": "медиапрогноз"}.get(intent, "кампанию")
            bot.reply_to(m, "Собираю %s: %s" % (label, req["url"]))
            _start_job(m, intent, req)
            return
        except ValueError:
            pass

        # 3) не понял -> меню
        bot.reply_to(m, "Не понял, но вот что я умею 👇")
        bot.send_message(m.chat.id, ui.WELCOME, parse_mode="HTML",
                         reply_markup=ui.main_menu())

    bot.infinity_polling(timeout=25, long_polling_timeout=20)


def _uptime() -> str:
    import time
    secs = int(time.time() - _START_TS)
    if secs < 60:
        return "%d c" % secs
    if secs < 3600:
        return "%d мин" % (secs // 60)
    return "%d ч %d мин" % (secs // 3600, (secs % 3600) // 60)


_START_TS = __import__("time").time()


if __name__ == "__main__":
    main()
