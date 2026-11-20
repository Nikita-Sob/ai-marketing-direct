# -*- coding: utf-8 -*-
"""Регрессия: тексты объявлений не обрываются посреди фразы."""
import unittest

from app.ads import generate_group_ad
from app.validator import LIMITS, commander_len

LONG_USPS = [
    "Прямые поставки от производителей — без посредников, наценок и подделок",
    "Консультации до и после покупки, помощь при настройке и эксплуатации",
    "Быстрая доставка Доставим на следующий день, в удобное для Вас время",
]
BAD_ENDINGS = (" по.", " по России", " в.", " и.", " на.", " с.")


def _ads(usps):
    card = {"brand": "Тест", "domain": "test.ru", "url": "https://test.ru", "usps": usps, "categories": []}
    names = ["рации", "аккумуляторы для раций", "коаксиальный кабель", "антенны"]
    return [generate_group_ad({"base": n, "category": {}}, card, i)
            for i, n in enumerate(names)]


class TestAdTexts(unittest.TestCase):
    def _check(self, text):
        self.assertLessEqual(commander_len(text), LIMITS["text"], text)
        self.assertTrue(text.endswith((".", "!", "?")), text)
        self.assertFalse(any(text.endswith(b) or (b + ".") in text for b in BAD_ENDINGS), text)
        # доставка либо целиком, либо отсутствует
        if "Доставка по" in text:
            self.assertIn("Доставка по России.", text)

    def test_long_usps_never_cut_delivery(self):
        for ad in _ads(LONG_USPS):
            self._check(ad["text"])
            for t in ad["combo_texts"]:
                self._check(t)

    def test_no_usps_fallback(self):
        for ad in _ads([]):
            self._check(ad["text"])
            self.assertEqual(len(ad["combo_texts"]), 3)

    def test_usps_rotate_between_groups(self):
        texts = {ad["text"] for ad in _ads(LONG_USPS)}
        self.assertGreater(len(texts), 1)


if __name__ == "__main__":
    unittest.main()
