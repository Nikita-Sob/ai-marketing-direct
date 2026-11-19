"""Тесты парсера сообщений Telegram-бота (без сети и без Telegram)."""

import unittest

from app.bot import parse_request
from app.ui import DEFAULT_REGION


class TestParse(unittest.TestCase):
    def test_full_form(self):
        r = parse_request("кампания: https://duplex-shop.ru | рации для охоты | Москва и область")
        self.assertEqual(r["url"], "https://duplex-shop.ru")
        self.assertEqual(r["brief"], "рации для охоты")
        self.assertEqual(r["region"], "Москва и область")
        self.assertTrue(r["combo"])  # комбинаторика по умолчанию

    def test_no_region(self):
        r = parse_request("кампания: https://kuppersberg.ru | встраиваемая техника")
        self.assertEqual(r["region"], DEFAULT_REGION)

    def test_bare_url(self):
        r = parse_request("https://kuppersberg.ru | техника")
        self.assertEqual(r["url"], "https://kuppersberg.ru")
        self.assertEqual(r["brief"], "техника")

    def test_combo_default_and_off(self):
        r = parse_request("кампания: https://kuppersberg.ru | техника")
        self.assertTrue(r["combo"])  # 7 заголовков + 3 текста по умолчанию
        r = parse_request("кампания: https://kuppersberg.ru | техника | без комбо")
        self.assertFalse(r["combo"])
        r = parse_request("кампания: https://kuppersberg.ru | техника просто")
        self.assertFalse(r["combo"])

    def test_domain_without_scheme(self):
        r = parse_request("кампания: duplex-shop.ru | рации")
        self.assertEqual(r["url"], "duplex-shop.ru")

    def test_no_space_after_colon(self):
        r = parse_request("кампания:https://x.ru|бриф")
        self.assertEqual(r["url"], "https://x.ru")
        self.assertEqual(r["brief"], "бриф")

    def test_extra_spaces(self):
        r = parse_request("кампания:   https://x.ru   |   бриф   ")
        self.assertEqual(r["url"], "https://x.ru")
        self.assertEqual(r["brief"], "бриф")

    def test_bad(self):
        for bad in ("", "   ", "кампания:", "привет как дела"):
            with self.assertRaises(ValueError):
                parse_request(bad)


if __name__ == "__main__":
    unittest.main()
