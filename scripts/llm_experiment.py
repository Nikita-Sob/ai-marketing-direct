# -*- coding: utf-8 -*-
"""Эксперимент для слайда 6: сравнение генерации текстов (LLM vs правила)
и двух режимов семантики (шаблоны vs Wordstat).

Запуск (один раз, на сервере, с env-ключами):
    .venv/bin/python scripts/llm_experiment.py

Результат: scripts/fixtures/llm_vs_rules.json — фикстуры для офлайн-теста
tests/test_llm_compare.py. Тесты в сети и ключах не нуждаются: они сверяют
записанные результаты эксперимента с пересчётом по сохранённым текстам.

LLM: GLM-5.3 через inference API Nous (ключ из /root/.hermes/auth.json).
Это одноразовый эксперимент для обоснования выбора инструментов, в основной
сценарий продукта LLM не входит (ADS_LLM_HOOK не активен).
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ads, semantics
from app.validator import Ad, validate_ad, is_ok, commander_len, LIMITS

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "fixtures", "llm_vs_rules.json")

# --- минимальный LLM-клиент (inference API Nous, как в Food Brain) ---
AUTH_PATH = "/root/.hermes/auth.json"
BASE_URL = "https://inference-api.nousresearch.com/v1"
MODEL = "z-ai/glm-5.3"


def _llm(prompt: str) -> str:
    d = json.load(open(AUTH_PATH))["providers"]["nous"]
    key = d.get("agent_key") or d["access_token"]
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "max_tokens": 4000,
            "reasoning_effort": "low",
        }).encode(),
        headers={"Authorization": "Bearer %s" % key,
                 "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=180))
    return r["choices"][0]["message"]["content"]


def llm_group_ad(base: str, card: dict) -> dict:
    """Один и тот же промпт, что и правила: группа + карточка бизнеса."""
    usps = "; ".join(card["usps"][:3]) or "низкие цены, доставка по России"
    prompt = (
        "Составь объявление Яндекс Директа для поиска. Товарная группа: «%s». "
        "Магазин: %s (%s). Преимущества с сайта: %s.\n"
        "Требования Директа: Заголовок 1 не длиннее 56 символов, Заголовок 2 не "
        "длиннее 30, Текст не длиннее 81, у текстов в конце точка. "
        "Плюс 7 вариантов Заголовка 1 (до 56) и 3 варианта Текста (до 81).\n"
        "Ответ: СТРОГО JSON вида {\"h1\":..., \"h2\":..., \"text\":..., "
        "\"heads\":[7 шт], \"texts\":[3 шт]} без markdown и пояснений."
        % (base, card["brand"], card.get("domain", "shop"), usps))
    raw = _llm(prompt).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def violations(ad: dict) -> list:
    """Список нарушений валидатора по основному объявлению (h1/h2/text)."""
    a = Ad(h1=str(ad.get("h1", "")), h2=str(ad.get("h2", "")),
           text=str(ad.get("text", "")),
           display_url=str(ad.get("display_url", "shop.ru")))
    return [i.message for i in validate_ad(a) if i.level == "ERR"]


def combo_violations(ad: dict) -> int:
    """Сколько из 7+3 вариантов комбинаторики ломают лимиты."""
    bad = 0
    for h in ad.get("heads", []):
        if commander_len(str(h)) > LIMITS["h1"]:
            bad += 1
    for t in ad.get("texts", []):
        if commander_len(str(t)) > LIMITS["text"]:
            bad += 1
    return bad


def main() -> None:
    from test_card import CARD, BASES  # фиксированный ввод эксперимента

    out = {"meta": {"model": MODEL, "ts": time.strftime("%Y-%m-%d %H:%M"),
                    "prompt_card": CARD}, "groups": []}

    # --- 1. LLM vs правила на одинаковых группах, по 2 прогона LLM ---
    for base in BASES:
        rules_ad = ads.generate_group_ad({"base": base, "category": {}}, CARD, 0)
        llm_runs, llm_texts = [], []
        for _ in range(2):
            t0 = time.time()
            a = llm_group_ad(base, CARD)
            dt = round(time.time() - t0, 1)
            llm_runs.append({
                "ad": a,
                "seconds": dt,
                "err": violations(a),
                "combo_bad": combo_violations(a),
            })
            llm_texts.append(json.dumps(a, sort_keys=True, ensure_ascii=False))
        out["groups"].append({
            "base": base,
            "rules": {
                "ad": {k: rules_ad[k] for k in ("h1", "h2", "text")},
                "err": violations(rules_ad),
                "combo_bad": combo_violations(
                    {"heads": rules_ad["combo_heads"],
                     "texts": rules_ad["combo_texts"]}),
                "seconds": 0.0,
            },
            "llm": llm_runs,
            "llm_deterministic": llm_texts[0] == llm_texts[1],
        })

    # --- 2. Режимы семантики: шаблоны vs живой Wordstat ---
    if os.environ.get("YANDEX_SEARCH_API_KEY"):
        from app import wordstat
        sem = {}
        for mode, use_ws in (("templates", False), ("wordstat", True)):
            groups = semantics.build_groups(
                CARD, BASES[0], use_wordstat=use_ws,
                log=lambda *a: None)
            sem[mode] = {
                g["base"]: g["phrases"] for g in groups
                if g["base"] == BASES[0]
            } and [g["phrases"] for g in groups if g["base"] == BASES[0]][0]
        out["semantics"] = {
            "templates": sem["templates"],
            "wordstat": sem["wordstat"],
            "wordstat_available": wordstat.available(),
        }
    else:
        out["semantics"] = {"wordstat_available": False,
                            "note": "нет ключа YANDEX_SEARCH_API_KEY"}

    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved", FIXTURE)


if __name__ == "__main__":
    main()
