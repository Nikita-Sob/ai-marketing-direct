# -*- coding: utf-8 -*-
"""Фиксированный ввод эксперимента llm_vs_rules: карточка и группы.

Одна и та же карточка и группы подаются и генератору на правилах, и LLM.
"""
CARD = {
    "brand": "Тест Шоп",
    "domain": "test-shop.ru",
    "url": "https://test-shop.ru",
    "phone": "+7 495 123 45 67",
    "categories": [
        {"name": "Рации", "url": "https://test-shop.ru/racii"},
        {"name": "Аккумуляторы", "url": "https://test-shop.ru/akkumulyatory"},
        {"name": "Антенны", "url": "https://test-shop.ru/antenny"},
        {"name": "Кабель", "url": "https://test-shop.ru/kabel"},
    ],
    "usps": [
        "Прямые поставки от производителей: без посредников и наценок",
        "Гарантия 24 месяца на все товары",
        "Доставка по всей России за 1-2 дня",
    ],
}

BASES = ["рации для охоты", "цифровые рации", "аккумуляторы для раций"]
