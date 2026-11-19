"""Тесты UI-слоя бота: клавиатуры, прогресс, HTML-сводки."""

import unittest

from app import ui


def fake_campaign_res():
    g1 = {"name": "рации_для_охоты", "phrases": [1]*8, "minus_group": []}
    g2 = {"name": "цифровые_рации", "phrases": [1]*7, "minus_group": []}
    rep = {"rows": 51, "err": [], "warn": []}
    c = {"url": "https://duplex-shop.ru", "region": "Москва и область",
         "groups": [g1, g2]}
    return {"campaign": c, "report": rep}


class TestKeyboards(unittest.TestCase):
    def test_all_kb_valid_json(self):
        import json
        for kb in (ui.main_menu(), ui.cancel_kb(), ui.skip_kb(), ui.region_kb(),
                   ui.after_campaign_kb(), ui.after_seo_kb(), ui.after_forecast_kb(),
                   ui.error_kb()):
            self.assertIsInstance(kb, str)  # сериализованный JSON
            d = json.loads(kb)
            self.assertIn("inline_keyboard", d)
            for row in d["inline_keyboard"]:
                for btn in row:
                    self.assertIn("text", btn)
                    self.assertIn("callback_data", btn)
                    self.assertLessEqual(len(btn["callback_data"].encode()), 64)

    def test_callbacks_unique_enough(self):
        import json
        d = json.loads(ui.main_menu())
        datas = [b["callback_data"] for row in d["inline_keyboard"] for b in row]
        self.assertEqual(len(datas), len(set(datas)))


class TestProgress(unittest.TestCase):
    def test_stage_mapping(self):
        self.assertIn("Обхожу сайт", ui.stage_text("1/4 краулер: https://x.ru"))
        self.assertIn("Семантика", ui.stage_text("2/4 семантика"))
        self.assertIn("объявления", ui.stage_text("3/4 объявления"))
        self.assertIn("XLSX", ui.stage_text("4/4 сборка XLSX"))
        self.assertIsNone(ui.stage_text("wordstat рации: 7 фраз"))
        self.assertIsNone(ui.stage_text("мусорная строка"))


class TestHtml(unittest.TestCase):
    def test_esc(self):
        self.assertEqual(ui.esc("<b>&"), "&lt;b&gt;&amp;")

    def test_campaign_html(self):
        h = ui.campaign_html(fake_campaign_res())
        self.assertIn("<b>Кампания готова</b>", h)
        self.assertIn("duplex-shop.ru", h)
        self.assertNotIn("<", h.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
        self.assertIn("Групп: 2", h)

    def test_seo_html(self):
        res = {"card": {"url": "https://x.ru"},
               "core": [{"rows": [1]*12}, {"rows": [1]*5}],
               "gaps": [1]*33, "metas": [1]*15,
               "plan": [{"title": "Холодильник двухкамерный", "freq": 152642}]}
        h = ui.seo_html(res)
        self.assertIn("SEO-отчёт готов", h)
        self.assertIn("17 фраз", h)
        self.assertIn("Холодильник двухкамерный", h)
        self.assertIn("152 642", h)

    def test_forecast_html_keeps_table(self):
        text = ("МЕДИАПРОГНОЗ КАМПАНИИ\n"
                "Группа     Показов  Кликов\n"
                "----\n"
                "рации      1 700    170\n"
                "ИТОГО      1 700    170\n"
                "Конверсий в месяц: 8.5\n"
                "Допущения модели")
        h = ui.forecast_html(text)
        self.assertIn("<pre>", h)
        self.assertIn("ИТОГО", h)


if __name__ == "__main__":
    unittest.main()
