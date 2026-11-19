import unittest
from app.validator import (
    Ad, Issue, commander_len, validate_ad, validate_phrase, validate_group, is_ok,
)


def errs(issues):
    return [i for i in issues if i.level == "ERR"]


class TestCommanderLen(unittest.TestCase):
    """Паритет с формулой шаблона: LEN(SUBSTITUTE(...)) по символам ! , . ; : и кавычке."""

    def test_punct_removed(self):
        # "Привет, мир! Тест." = 18 символов, минус , ! . = 15
        self.assertEqual(commander_len("Привет, мир! Тест."), 15)

    def test_quotes_removed(self):
        self.assertEqual(commander_len('"Рации" для охоты: купить;'), len("Рации для охоты купить"))

    def test_empty(self):
        self.assertEqual(commander_len(""), 0)
        self.assertEqual(commander_len(None), 0)

    def test_no_punct(self):
        self.assertEqual(commander_len("рации для охоты"), 15)


class TestAd(unittest.TestCase):
    def test_good_ad(self):
        ad = Ad(h1="Купить рации для охоты", h2="В наличии",
                text="Оригинальные радиостанции с гарантией. Доставка по России.")
        self.assertTrue(is_ok(validate_ad(ad)))

    def test_h1_over_limit(self):
        # 57 букв без пунктуации: ERR; 57 символов, из них 2 запятые: проходит
        ad = Ad(h1="а" * 57, text="текст")
        self.assertTrue(any(i.field == "h1" for i in errs(validate_ad(ad))))
        ad2 = Ad(h1="а" * 55 + ",,", text="текст")
        self.assertEqual(commander_len(ad2.h1), 55)
        self.assertFalse(any(i.field == "h1" for i in errs(validate_ad(ad2))))

    def test_exact_limits(self):
        ad = Ad(h1="а" * 56, h2="б" * 30, text="в" * 81)
        self.assertTrue(is_ok(validate_ad(ad)))

    def test_over_limits(self):
        ad = Ad(h1="а" * 56, h2="б" * 31, text="в" * 82)
        e = errs(validate_ad(ad))
        self.assertEqual(len(e), 2)

    def test_empty_required(self):
        e = errs(validate_ad(Ad()))
        self.assertEqual(len(e), 2)  # h1 и text

    def test_h2_without_h1(self):
        e = errs(validate_ad(Ad(h2="В наличии", text="текст")))
        self.assertTrue(any("заголовок 2 без заголовка 1" in i.message for i in e))

    def test_display_url(self):
        ok = Ad(h1="a", text="b", display_url="kupit-racii")
        self.assertTrue(is_ok(validate_ad(ok)))
        bad_space = Ad(h1="a", text="b", display_url="купить рации")
        self.assertTrue(any(i.field == "display_url" for i in errs(validate_ad(bad_space))))
        bad_http = Ad(h1="a", text="b", display_url="https://duplex-shop.ru")
        self.assertTrue(any(i.field == "display_url" for i in errs(validate_ad(bad_http))))
        bad_long = Ad(h1="a", text="b", display_url="x" * 21)
        self.assertTrue(any(i.field == "display_url" for i in errs(validate_ad(bad_long))))

    def test_quick_links(self):
        good = [("Рации", "Большой выбор", "/racii"), ("Антенны", "В наличии", "/antenny"),
                ("Гарнитуры", "Гарантия 2 года", "/garnitury"),
                ("АКБ", "Доставка по РФ", "/akkumulyatory")]
        ad = Ad(h1="a", text="b", quick_links=good)
        self.assertTrue(is_ok(validate_ad(ad)))
        ad3 = Ad(h1="a", text="b", quick_links=good[:3])
        self.assertTrue(any("от 4 до 8" in i.message for i in errs(validate_ad(ad3))))
        long_h = [("Р" * 31, "ок", "/x")] * 4
        self.assertTrue(any("заголовок ссылки" in i.message for i in errs(validate_ad(Ad(h1="a", text="b", quick_links=long_h)))))
        long_d = [("ок", "Д" * 31, "/x")] * 4
        self.assertTrue(any("описание ссылки" in i.message for i in errs(validate_ad(Ad(h1="a", text="b", quick_links=long_d)))))
        # ровно 30 проходит
        ok_d = [("ок", "Д" * 30, "/x")] * 4
        self.assertFalse(any("описание ссылки" in i.message for i in errs(validate_ad(Ad(h1="a", text="b", quick_links=ok_d)))))


class TestPhrase(unittest.TestCase):
    def test_good(self):
        self.assertTrue(is_ok(validate_phrase("рации +для охоты")))
        self.assertTrue(is_ok(validate_phrase("---autotargeting")))

    def test_only_minus(self):
        self.assertFalse(is_ok(validate_phrase("-рации -для")))

    def test_uppercase_warn(self):
        issues = validate_phrase("Рации для охоты")
        self.assertFalse(errs(issues))
        self.assertTrue(any(i.level == "WARN" for i in issues))

    def test_uppercase_with_operator_ok(self):
        self.assertTrue(is_ok(validate_phrase("!Рации для охоты")))

    def test_empty(self):
        self.assertFalse(is_ok(validate_phrase("  ")))

    def test_lone_dash(self):
        self.assertFalse(is_ok(validate_phrase("рации -")))


class TestGroup(unittest.TestCase):
    def test_dupe_phrase(self):
        issues = validate_group("охота", ["рации для охоты", "РАЦИИ ДЛЯ ОХОТЫ"])
        self.assertTrue(any("дубликат" in i.message for i in issues))

    def test_empty_name(self):
        self.assertFalse(is_ok(validate_group("", ["фраза"])))


if __name__ == "__main__":
    unittest.main()
