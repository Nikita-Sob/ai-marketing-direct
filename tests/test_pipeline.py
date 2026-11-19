"""Офлайн-тесты конвейера: краулер, семантика, объявления, сборка XLSX.

Сеть не нужна: HTTP подменяется фикстурой, Wordstat выключен (--no-wordstat
логика) или подменяется. Сборка XLSX идёт по реальному шаблону Коммандера.
"""

import tempfile
import unittest
from unittest import mock

from app import ads, builder, crawler, semantics
from app.validator import Ad, validate_ad, is_ok, commander_len


FIXTURE_HTML = """
<html><head><title>Тест Шоп - магазин тестовых раций и антенн</title>
<meta name="description" content="Магазин тестовых раций. Гарантия 2 года. Доставка по России бесплатно."></head>
<body>
<nav>
<a href="/shop/category/raczii/">Рации 25</a>
<a href="/shop/category/raczii/czifrovye-raczii">Цифровые рации 12</a>
<a href="/shop/category/antenny/">Антенны 8</a>
<a href="/shop/product/racziya-turbo-6/">Turbo 6</a>
<a href="/product_brand/turbo/">Turbo</a>
<a href="/garantiya-i-vozvrat/">Гарантия и возврат</a>
<a href="/dostavka-i-oplata/">Доставка и оплата</a>
<a href="/kontakty/">Контакты +7 495 123 45 67</a>
</nav>
<p>Прямые поставки от производителей: без посредников и наценок. Гарантия 24 месяца на все товары.</p>
</body></html>
"""


def fake_card():
    return {
        "url": "https://test-shop.ru",
        "domain": "test-shop.ru",
        "brand": "Тест Шоп",
        "title": "Тест Шоп - магазин тестовых раций и антенн",
        "description": "Магазин тестовых раций. Гарантия 2 года. Доставка по России бесплатно.",
        "categories": [
            {"name": "Рации", "url": "https://test-shop.ru/shop/category/raczii/"},
            {"name": "Цифровые рации", "url": "https://test-shop.ru/shop/category/raczii/czifrovye-raczii"},
            {"name": "Антенны", "url": "https://test-shop.ru/shop/category/antenny/"},
        ],
        "usps": [
            "Прямые поставки от производителей: без посредников и наценок.",
            "Гарантия 24 месяца на все товары.",
        ],
        "phone": "+7 495 123 45 67",
        "text_sample": "",
    }


class TestCrawler(unittest.TestCase):
    def test_fetch_card(self):
        with mock.patch.object(crawler, "_get", return_value=FIXTURE_HTML):
            card = crawler.fetch_business_card("https://test-shop.ru")
        self.assertEqual(card["brand"], "Тест Шоп")
        names = [c["name"] for c in card["categories"]]
        self.assertIn("Рации", names)
        self.assertIn("Цифровые рации", names)
        self.assertIn("Антенны", names)
        self.assertNotIn("Turbo 6", names)      # товары
        self.assertNotIn("Turbo", names)        # бренды
        self.assertNotIn("Гарантия и возврат", names)  # служебное
        self.assertNotIn("Доставка и оплата", names)
        self.assertTrue(any("доставк" in u.lower() or "гарант" in u.lower() for u in card["usps"]))
        self.assertIn("+7 495", card["phone"])


class TestSemantics(unittest.TestCase):
    def test_monobrand_filter(self):
        mono = fake_card()
        mono["domain"] = "kuppersberg.ru"
        mono["brand"] = "Kuppersberg"
        rows = [("варочные панели", 100), ("варочная панель bosch", 50),
                ("холодильник атлант", 30)]
        kept = semantics.drop_competitor_brands(rows, mono)
        self.assertEqual([p for p, _ in kept], ["варочные панели"])
        # мультибрендовый магазин: бренды не режем
        multi = fake_card()
        multi["domain"] = "duplex-shop.ru"
        multi["brand"] = "Дуплекс Шоп"
        self.assertEqual(len(semantics.drop_competitor_brands(rows, multi)), 3)

    def test_patterns_no_wordstat(self):
        groups = semantics.build_groups(fake_card(), brief="рации для охоты",
                                        use_wordstat=False, log=lambda *a: None)
        self.assertEqual(groups[0]["base"], "рации для охоты")
        self.assertEqual(groups[0]["phrases"][0], "---autotargeting")
        # стоп-слова с +
        self.assertIn("рации +для охоты", groups[0]["phrases"])
        self.assertIn("купить рации +для охоты", groups[0]["phrases"])
        # кросс-минусация
        self.assertIn("-антенны", groups[0]["minus_group"])
        # группы без дублей фраз
        for g in groups:
            self.assertEqual(len(g["phrases"]), len(set(g["phrases"])))

    def test_junk_filter(self):
        self.assertTrue(semantics._is_junk("рация для охоты рейтинг 2026"))
        self.assertTrue(semantics._is_junk("как выбрать рацию"))
        self.assertFalse(semantics._is_junk("купить рацию для охоты"))

    def test_wordstat_phrases(self):
        fake_top = {"totalCount": 100,
                    "results": [("рации для охоты", 500),
                                ("какая рация для охоты лучше", 300),
                                ("рации для охоты недорого купить", 100)],
                    "associations": []}
        with mock.patch.object(semantics.wordstat, "get_top", return_value=fake_top), \
             mock.patch.object(semantics.wordstat, "available", return_value=True):
            ph = semantics._wordstat_phrases("рации для охоты", 5)
        self.assertIn("рации +для охоты", ph)
        self.assertIn("рации +для охоты недорого купить", ph)
        self.assertNotIn("какая рация +для охоты лучше", ph)  # мусор отфильтрован

    def test_slug(self):
        self.assertEqual(semantics.group_slug("рации для охоты!"), "рации_для_охоты")


class TestAds(unittest.TestCase):
    def test_ad_passes_validator(self):
        groups = semantics.build_groups(fake_card(), brief="рации для охоты",
                                        use_wordstat=False, log=lambda *a: None)
        g = groups[0]
        ad = ads.generate_group_ad(g, fake_card(), 0)
        self.assertTrue(is_ok(validate_ad(Ad(h1=ad["h1"], h2=ad["h2"], text=ad["text"],
                                             display_url=ad["display_url"],
                                             quick_links=ad["quick_links"]))))
        self.assertEqual(len(ad["combo_heads"]), 7)
        self.assertEqual(len(ad["combo_texts"]), 3)
        for h in ad["combo_heads"]:
            self.assertLessEqual(commander_len(h), 56)
        for t in ad["combo_texts"]:
            self.assertLessEqual(commander_len(t), 81)
        self.assertTrue(4 <= len(ad["quick_links"]) <= 8)
        for h, d, u in ad["quick_links"]:
            self.assertLessEqual(commander_len(h), 30)
            self.assertLessEqual(commander_len(d), 60)
            self.assertTrue(u.startswith("http"))
        self.assertIn("{keyword}", ad["link"])  # UTM-плейсхолдеры
        self.assertLessEqual(commander_len(ad["display_url"]), 20)

    def test_minimal_card_no_categories(self):
        """Сайт без каталога (например, сайт застройщика): быстрые ссылки
        добираются служебными до 4, объявление валидно."""
        groups = semantics.build_groups(fake_card(), brief="виллы с патио и бассейном",
                                        use_wordstat=False, log=lambda *a: None)
        g = groups[0]
        card = fake_card()
        card["categories"] = []
        card["usps"] = []
        ad = ads.generate_group_ad(g, card, 0)
        self.assertGreaterEqual(len(ad["quick_links"]), 4)
        self.assertTrue(is_ok(validate_ad(Ad(h1=ad["h1"], h2=ad["h2"], text=ad["text"],
                                             display_url=ad["display_url"],
                                             quick_links=ad["quick_links"]))))

    def test_fit_limits_no_word_break(self):
        out = ads.fit_limits("Купить рации для охоты по очень привлекательным низким ценам", 20)
        self.assertLessEqual(commander_len(out), 20)
        self.assertTrue(out.startswith("Купить рации"))


class TestBuilder(unittest.TestCase):
    def _campaign(self):
        groups = semantics.build_groups(fake_card(), brief="рации для охоты",
                                        use_wordstat=False, log=lambda *a: None)
        for i, g in enumerate(groups[:3]):
            g["num"] = i + 1
            g["ad"] = ads.generate_group_ad(g, fake_card(), i)
        return {
            "url": "https://test-shop.ru",
            "region": "Москва и область",
            "phone": "+7 495 123 45 67",
            "campaign_minus": semantics.CAMPAIGN_MINUS,
            "groups": groups[:3],
            "brand": "Тест Шоп",
        }

    def test_build_and_validate(self):
        campaign = self._campaign()
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + "/out.xlsx"
            stats = builder.build_xlsx(campaign, path)
            # строк: (фразы + 1 вариант) на группу
            expect_rows = sum(len(g["phrases"]) + 1 for g in campaign["groups"])
            self.assertEqual(stats["rows"], expect_rows)
            rep = builder.validate_built_xlsx(path)
            self.assertEqual(rep["err"], [])
            # объявлений: строки фраз + строка вариантов "+" на группу
            self.assertEqual(rep["ads"],
                             sum(len(g["phrases"]) + 1 for g in campaign["groups"]))
            # в строке "+" тоже заполнены J/K/L (иначе Коммандер создаст пустое объявление)
            import openpyxl
            wb = openpyxl.load_workbook(path)
            ws = wb["Тексты"]
            r = builder.DATA_START
            seen_plus = 0
            while ws.cell(r, 1).value in ("-", "+"):
                if ws.cell(r, 1).value == "+":
                    self.assertTrue(ws.cell(r, builder.COL["J"]).value)
                    self.assertTrue(ws.cell(r, builder.COL["L"]).value)
                    seen_plus += 1
                r += 1
            self.assertEqual(seen_plus, len(campaign["groups"]))

    def test_minus_words_rules(self):
        """Слэш (б/у) и прочие запрещённые символы в минус-фразах = ERR,
        сборщик такие слова в файл не пишет."""
        from app.validator import validate_minus_words, is_ok
        bad = validate_minus_words(["!б/у", "!как", "!санкт-петербург?"])
        errs = [i for i in bad if i.level == "ERR"]
        self.assertTrue(any("/" in i.message for i in errs))
        self.assertTrue(is_ok(validate_minus_words(["!как", "!бу", "!рейтинг"])))
        # сборщик выкидывает битые слова
        self.assertEqual(builder._clean_minus(["!б/у", "!как", ""]),
                         ["!как"])
        self.assertEqual(builder._clean_minus(["аккумуляторы", "ан-тенны"]),
                         ["аккумуляторы", "ан-тенны"])

    def test_no_combo_single_ad(self):
        campaign = self._campaign()
        campaign["combo"] = False
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + "/out.xlsx"
            stats = builder.build_xlsx(campaign, path)
            import openpyxl
            wb = openpyxl.load_workbook(path)
            ws = wb["Тексты"]
            r = builder.DATA_START
            types = set()
            n_rows = 0
            while ws.cell(r, 1).value in ("-", "+"):
                types.add((ws.cell(r, 1).value, ws.cell(r, 2).value))
                if ws.cell(r, 1).value == "-":
                    n_rows += 1
                r += 1
            self.assertEqual(n_rows, stats["rows"])  # строк "+" нет вообще
            self.assertEqual(types, {("-", "Текстово-графическое")})
            rep = builder.validate_built_xlsx(path)
            self.assertEqual(rep["err"], [])

    def test_bad_region_rejected(self):
        campaign = self._campaign()
        campaign["region"] = "Атлантида"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                builder.build_xlsx(campaign, tmp + "/out.xlsx")


if __name__ == "__main__":
    unittest.main()
