"""Проверка парсера на сообщениях. Свои реальные примеры добавьте в SAMPLES: (текст, ожидаемая сумма | None)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.payments import parse_amount

SAMPLES = [
    # --- реальные сообщения @CardXabarBot ---
    ("🟢 Perevod na kartu\n➕ 100 000.00 UZS\n💳 ***2410\n📍 UZCARD TO UZCARD CLICK MKBANK PREMIUM, UZ\n🕓 01.11.26 16:11\n💵 106 331.13 UZS", 100000),
    ("🔴 Spisanie c karty\n➖ 90 990.00 UZS\n💳 ***2410\n📍 CLICK P2P, UZ\n🕓 01.11.26 17:27\n💵 15 341.13 UZS", None),
    # --- запасные форматы ---
    ("🟢 Perevod na kartu\n➕ 1 234 567.00 UZS\n💵 9 999 999.00 UZS", 1234567),
    ("🟢 Пополнение\n100 000,00 so'm\nБаланс: 900 000.00 UZS", 100000),
    ("Kirim: 25.037 so'm\nQoldiq: 1 025 037 so'm", 25037),
    ("🔴 Оплата 12 500 сум\nБаланс: 5 000 сум", None),
    ("Chiqim 80 000 so'm", None),
    ("Ваш код подтверждения: 123456", None),
]
bad = 0
for text, want in SAMPLES:
    got = parse_amount(text)
    ok = got == want
    bad += not ok
    print("OK " if ok else "BAD", repr(text[:40]), "->", got, "(ожидали", want, ")")
sys.exit(1 if bad else 0)
