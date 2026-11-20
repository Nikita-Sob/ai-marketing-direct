# -*- coding: utf-8 -*-
"""Сравнение генерации на правилах и LLM (слайд 6) — офлайн, по фикстурам.

Фикстура scripts/fixtures/llm_vs_rules.json записана одноразовым
экспериментом scripts/llm_experiment.py (LLM GLM-5.3, 2 одинаковых прогона
на группу). Тест пересчитывает нарушения валидатора по сохранённым текстам
и сверяет с записанными результатами: воспроизводится без сети и ключей.
"""
import json
import os
import unittest

from app.validator import Ad, validate_ad, commander_len, LIMITS

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts", "fixtures", "llm_vs_rules.json")


def _err_count(ad: dict) -> int:
    a = Ad(h1=str(ad.get("h1", "")), h2=str(ad.get("h2", "")),
           text=str(ad.get("text", "")), display_url="shop.ru")
    return sum(1 for i in validate_ad(a) if i.level == "ERR")


def _combo_bad(ad: dict) -> int:
    bad = 0
    for h in ad.get("heads", []):
        if commander_len(str(h)) > LIMITS["h1"]:
            bad += 1
    for t in ad.get("texts", []):
        if commander_len(str(t)) > LIMITS["text"]:
            bad += 1
    return bad


@unittest.skipUnless(os.path.exists(FIXTURE), "нет фикстуры эксперимента")
class TestLLMVsRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, encoding="utf-8") as f:
            cls.data = json.load(f)
        print("\n=== LLM vs правила (слайд 6) ===")
        print("%-28s %-22s %-38s" % ("группа", "правила (err/combo)", "LLM: err/combo по 2 прогонам, повтор"))
        for g in cls.data["groups"]:
            r = g["rules"]
            l = g["llm"]
            print("%-28s %-22s %-38s" % (
                g["base"][:26],
                "%d / %d" % (len(r["err"]), r["combo_bad"]),
                "%s, повтор: %s" % (
                    ", ".join("%d/%d" % (len(x["err"]), x["combo_bad"]) for x in l),
                    "да" if g["llm_deterministic"] else "нет")))

    def test_fixture_groups_present(self):
        self.assertGreaterEqual(len(self.data["groups"]), 3)

    def test_rules_zero_violations(self):
        """Генератор на правилах не нарушает лимиты — гарантия валидатора."""
        for g in self.data["groups"]:
            r = g["rules"]
            self.assertEqual(_err_count(r["ad"]), 0, g["base"])
            self.assertEqual(r["combo_bad"], 0, g["base"])

    def test_llm_recorded_stats_consistent(self):
        """Записанные результаты LLM совпадают с пересчётом по текстам."""
        for g in self.data["groups"]:
            for run in g["llm"]:
                self.assertEqual(len(run["err"]), _err_count(run["ad"]),
                                 g["base"])
                self.assertEqual(run["combo_bad"], _combo_bad(run["ad"]),
                                 g["base"])

    def test_llm_nondeterministic(self):
        """LLM даёт разный текст на одинаковый вход — повторяемость (STP)
        невозможна без пост-обработки. Это ключевое обоснование выбора."""
        det = [g["llm_deterministic"] for g in self.data["groups"]]
        self.assertTrue(any(not d for d in det), "LLM должен быть недетерминирован")

    def test_semantics_modes_recorded(self):
        """Режимы семантики зафиксированы (шаблоны и Wordstat на одном брифе)."""
        sem = self.data.get("semantics", {})
        if sem.get("wordstat_available"):
            self.assertIn("templates", sem)
            self.assertIn("wordstat", sem)
            self.assertTrue(sem["templates"])
            self.assertTrue(sem["wordstat"])
        else:
            self.assertIn("note", sem)


if __name__ == "__main__":
    unittest.main()
