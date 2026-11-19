"""Офлайн-тесты SEO-модуля и медиапрогноза (Wordstat подменяется)."""

import unittest

from app import forecast, seo
from app.bot import parse_intent, parse_request
from app.semantics import filter_results


def fake_card():
    return {
        "url": "https://test-shop.ru",
        "domain": "test-shop.ru",
        "brand": "Тест Шоп",
        "title": "Тест Шоп",
        "description": "",
        "categories": [
            {"name": "Рации", "url": "https://test-shop.ru/catalog/raczii/"},
            {"name": "Антенны", "url": "https://test-shop.ru/catalog/antenny/"},
        ],
        "usps": ["Гарантия 24 месяца на все товары."],
        "phone": "",
        "text_sample": "",
    }


FAKE_TOP = {
    "totalCount": 100,
    "results": [
        ("рации для охоты", 500),
        ("рации для охоты недорого купить", 200),
        ("какая рация для охоты лучше", 300),   # мусор
        ("рации для рыбалки", 150),
        ("носимые рации", 90),                   # «рации» покрыто категорией
    ],
    "associations": [],
}


class TestIntent(unittest.TestCase):
    def test_intents(self):
        self.assertEqual(parse_intent("seo: site.ru | рации"), "seo")
        self.assertEqual(parse_intent("СЕО site.ru"), "seo")
        self.assertEqual(parse_intent("прогноз: site.ru | тема"), "forecast")
        self.assertEqual(parse_intent("медиапрогноз site.ru"), "forecast")
        self.assertEqual(parse_intent("кампания: site.ru | бриф"), "campaign")
        self.assertEqual(parse_intent("https://site.ru | бриф"), "campaign")

    def test_parse_with_intent(self):
        r = parse_request("seo: https://x.ru | рации", parse_intent("seo: https://x.ru | рации"))
        self.assertEqual(r["url"], "https://x.ru")
        self.assertEqual(r["brief"], "рации")
        f = parse_request("прогноз: https://x.ru | техника | Москва и область",
                          "forecast")
        self.assertEqual(f["region"], "Москва и область")
        self.assertFalse(f["combo"])


class TestFilterResults(unittest.TestCase):
    def test_freqs_kept(self):
        rows = filter_results(FAKE_TOP["results"], "рации для охоты", 10)
        phrases = [ph for ph, _ in rows]
        self.assertIn("рации +для охоты", phrases)
        self.assertIn("рации +для охоты недорого купить", phrases)
        self.assertNotIn("какая рация +для охоты лучше", phrases)
        self.assertIn(500, [fr for _, fr in rows])
        # «носимые рации» не содержат все слова базы
        self.assertNotIn("носимые рации", phrases)


class TestGap(unittest.TestCase):
    def _core(self):
        return [
            {"name": "рации_для_охоты", "base": "рации для охоты",
             "rows": filter_results(FAKE_TOP["results"], "рации для охоты", 10)},
            {"name": "рации_для_рыбалки", "base": "рации для рыбалки",
             "rows": filter_results(FAKE_TOP["results"], "рации для рыбалки", 10)},
        ]

    def test_gap_finds_uncovered(self):
        card = fake_card()
        gaps = seo.gap_analysis(self._core(), card)
        phrases = [g["phrase"] for g in gaps]
        # «рации для охоты» и «рации для рыбалки» не покрыты страницами сайта
        self.assertIn("рации +для охоты", phrases)
        self.assertIn("рации +для рыбалки", phrases)
        # сортировка по частоте
        freqs = [g["freq"] for g in gaps]
        self.assertEqual(freqs, sorted(freqs, reverse=True))

    def test_content_plan(self):
        card = fake_card()
        gaps = seo.gap_analysis(self._core(), card)
        plan = seo.content_plan(gaps, self._core())
        self.assertTrue(plan)
        self.assertTrue(all(p["structure"] for p in plan))
        self.assertTrue(all(p["format"] in ("статья в блог", "посадочная категория")
                            for p in plan))
        self.assertLessEqual(len(plan[0]["title"]), 100)


class TestMeta(unittest.TestCase):
    def test_meta_lengths(self):
        metas = seo.meta_tags(fake_card(), [])
        self.assertEqual(len(metas), 2)
        for m in metas:
            self.assertLessEqual(len(m["title"]), 70)
            self.assertLessEqual(len(m["description"]), 160)
            self.assertIn("Тест Шоп", m["title"])


class TestForecast(unittest.TestCase):
    def test_region_ids(self):
        self.assertEqual(forecast.region_to_id("Москва и область"), "213")
        self.assertEqual(forecast.region_to_id("Россия"), "225")
        self.assertEqual(forecast.region_to_id("Атлантида"), "225")

    def test_math(self):
        core = [{"name": "g1", "base": "x",
                 "rows": [("фраза", 1000), ("фраза 2", 1000)]}]
        fc = forecast.forecast_campaign(core, {"ctr": 0.1, "cpc": 50.0, "cr": 0.05})
        g = fc["groups"][0]
        # показы = 2000 * 0.85 = 1700; клики = 170; расход = 170*50*1.2 = 10200
        self.assertEqual(g["shows"], 1700)
        self.assertEqual(g["clicks"], 170)
        self.assertEqual(g["cost"], 10200)
        self.assertEqual(g["conv"], 8.5)
        # CPA = 10200 / 8.5
        self.assertAlmostEqual(g["cpa"], 1200.0, places=1)
        self.assertEqual(fc["total"]["cost"], 10200)

    def test_defaults_kept(self):
        fc = forecast.forecast_campaign([{"name": "g", "base": "b", "rows": []}])
        self.assertEqual(fc["params"]["ctr"], forecast.DEFAULTS["ctr"])
        self.assertEqual(fc["params"]["cpc"], forecast.DEFAULTS["cpc"])

    def test_render(self):
        core = [{"name": "g1", "base": "x", "rows": [("фраза", 1000)]}]
        text = forecast.render_forecast(forecast.forecast_campaign(core),
                                        "https://x.ru", "Москва и область")
        self.assertIn("МЕДИАПРОГНОЗ", text)
        self.assertIn("Допущения модели", text)
        self.assertIn("ИТОГО", text)
        self.assertIn("213", text)


if __name__ == "__main__":
    unittest.main()
