"""Разбор уведомлений @CardXabarBot. Формат у разных банков/версий бота отличается —
проверьте регулярки на реальных сообщениях (см. README, раздел «Проверка парсера»)."""
import re

AMOUNT_RE = re.compile(r"(\d[\d \u00a0.,]*)\s*(?:UZS|сум|сўм|so['’`ʻ]?m)", re.I)
IN_WORDS = ("пополнение", "поступление", "зачисление", "popolnenie", "kirim", "➕", "credit")
OUT_WORDS = ("оплата", "списание", "снятие", "chiqim", "➖", "purchase", "payment", "debit")
SKIP_LINE = re.compile(r"баланс|balans|balance|остаток|qoldiq", re.I)


def parse_amount(text: str) -> int | None:
    low = text.lower()
    if not any(w in low for w in IN_WORDS):
        return None
    if any(w in low for w in OUT_WORDS) and not any(w in low for w in ("пополнение", "kirim", "popolnenie")):
        return None
    body = "\n".join(l for l in text.splitlines() if not SKIP_LINE.search(l))
    m = AMOUNT_RE.search(body)
    if not m:
        return None
    raw = re.sub(r"[ \u00a0]", "", m.group(1))
    raw = re.sub(r"[.,]\d{1,2}$", "", raw)     # копейки/тийины
    raw = re.sub(r"[.,]", "", raw)
    return int(raw) if raw.isdigit() and int(raw) > 0 else None
