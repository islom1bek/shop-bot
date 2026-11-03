"""Разбор уведомлений @CardXabarBot. Нужен ТОЛЬКО приход; расход и всё неясное игнорируется.

Реальный формат бота:
    🟢 Perevod na kartu          |  🔴 Spisanie c karty
    ➕ 100 000.00 UZS            |  ➖ 90 990.00 UZS     <- сумма операции (➕ приход / ➖ расход)
    💳 ***2410
    📍 ...
    🕓 01.11.26 16:11
    💵 106 331.13 UZS            <- ОСТАТОК на карте, не сумма операции
Проверка: python tests/check_parser.py"""
import re

NUM = r"(\d[\d \u00a0.,]*)"
PLUS_RE = re.compile(r"^\s*➕\s*" + NUM + r"\s*(?:UZS|сум|сўм|so['’`ʻ]?m)", re.I | re.M)
MINUS_RE = re.compile(r"^\s*➖", re.M)
# запасной разбор для сообщений без ➕/➖
AMOUNT_RE = re.compile(NUM + r"\s*(?:UZS|сум|сўм|so['’`ʻ]?m)", re.I)
IN_WORDS = ("пополнение", "поступление", "зачисление", "popolnenie", "kirim", "to'ldirish")
OUT_WORDS = ("оплата", "списание", "снятие", "расход", "spisanie", "oplata", "pokupka", "snyatie",
             "chiqim", "to'lov", "yechish", "purchase", "payment", "debit", "withdraw")
SKIP_LINE = re.compile(r"баланс|balans|balance|остаток|qoldiq|ostatok|💵|комисси|komissiya", re.I)


def _to_int(raw: str) -> int | None:
    raw = re.sub(r"[ \u00a0]", "", raw)
    raw = re.sub(r"[.,]\d{1,2}$", "", raw)         # тийины/копейки: 100 000.00 -> 100 000
    raw = re.sub(r"[.,]", "", raw)
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def parse_amount(text: str) -> int | None:
    if MINUS_RE.search(text) or "🔴" in text:       # расход — всегда игнор
        return None
    if m := PLUS_RE.search(text):                   # основной путь: строка «➕ сумма»
        return _to_int(m.group(1))
    low = text.lower()
    if any(w in low for w in OUT_WORDS) or not any(w in low for w in IN_WORDS):
        return None
    body = "\n".join(l for l in text.splitlines() if not SKIP_LINE.search(l))
    m = AMOUNT_RE.search(body)
    return _to_int(m.group(1)) if m else None
