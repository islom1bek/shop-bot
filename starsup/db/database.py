"""PostgreSQL (Neon-совместимо). Все операции с деньгами — в транзакции с FOR UPDATE."""
import re
from decimal import Decimal, ROUND_CEILING

import asyncpg

pool: asyncpg.Pool | None = None
SERVICE_DISABLED = "Сервис временно недоступен. Обратитесь в поддержку"
CATEGORIES = ("stars", "premium", "gifts")


class BotError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  tg_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT,
  balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  id SERIAL PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '⭐',
  base_price BIGINT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, sort INT NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders(
  id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(tg_id),
  product_id INT, category TEXT NOT NULL, title TEXT NOT NULL, price BIGINT NOT NULL,
  recipient TEXT, status TEXT NOT NULL DEFAULT 'processing',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS topups(
  id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(tg_id),
  amount BIGINT NOT NULL, base_amount BIGINT NOT NULL, method TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  source TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL, paid_at TIMESTAMPTZ);
CREATE UNIQUE INDEX IF NOT EXISTS topups_pending_amount ON topups(amount) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS balance_log(
  id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, delta BIGINT NOT NULL,
  balance_after BIGINT NOT NULL, reason TEXT NOT NULL, ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS bank_events(
  hash TEXT PRIMARY KEY, raw TEXT, amount BIGINT, matched_topup BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""

DEFAULTS = {
    "support_username": "", "card_uzcard": "", "card_humo": "", "card_holder": "",
    "markup_stars": "10", "markup_premium": "8", "markup_gifts": "12",
    "enabled_stars": "1", "enabled_premium": "1", "enabled_gifts": "1",
    "pay_uzcard": "1", "pay_humo": "1",
    "topup_min": "5000", "topup_max": "5000000", "topup_ttl_min": "20",
}

# ПРИМЕР каталога: закупочные цены в сумах — замените на свои (/setbase <id> <цена>)
SEED = [
    ("stars", "50 Stars", "⭐", 9000), ("stars", "100 Stars", "⭐", 18000),
    ("stars", "250 Stars", "⭐", 44000), ("stars", "500 Stars", "⭐", 88000),
    ("stars", "1000 Stars", "⭐", 175000),
    ("premium", "Premium · 3 месяца", "💎", 175000), ("premium", "Premium · 6 месяцев", "💎", 330000),
    ("premium", "Premium · 12 месяцев", "💎", 580000),
    ("gifts", "NFT-подарок «Мишка»", "🧸", 15000), ("gifts", "NFT-подарок «Сердце»", "💝", 15000),
    ("gifts", "NFT-подарок «Роза»", "🌹", 30000), ("gifts", "NFT-подарок «Торт»", "🎂", 30000),
]


async def init(dsn: str):
    global pool
    # statement_cache_size=0 — нужно для пулера Neon (pgbouncer)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10, statement_cache_size=0)
    async with pool.acquire() as c:
        await c.execute(SCHEMA)
        for k, v in DEFAULTS.items():
            await c.execute("INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT DO NOTHING", k, v)
        if not await c.fetchval("SELECT count(*) FROM products"):
            for i, (cat, title, emoji, price) in enumerate(SEED):
                await c.execute("INSERT INTO products(category,title,emoji,base_price,sort) VALUES($1,$2,$3,$4,$5)",
                                cat, title, emoji, price, i)


# ---------- настройки ----------
async def get_setting(key: str) -> str:
    v = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
    return v if v is not None else DEFAULTS.get(key, "")


async def set_setting(key: str, value: str):
    await pool.execute("INSERT INTO settings(key,value) VALUES($1,$2) "
                       "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", key, value)


async def get_settings() -> dict:
    rows = await pool.fetch("SELECT key,value FROM settings")
    return {**DEFAULTS, **{r["key"]: r["value"] for r in rows}}


async def toggle(key: str) -> bool:
    v = await pool.fetchval("UPDATE settings SET value = CASE WHEN value='1' THEN '0' ELSE '1' END "
                            "WHERE key=$1 RETURNING value", key)
    return v == "1"


async def support_url() -> str:
    u = (await get_setting("support_username")).strip()
    u = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)?@?", "", u)
    return f"https://t.me/{u}" if u else ""


def final_price(base: int, markup_pct) -> int:
    """Закупка + наценка %, округление вверх до 100 сум."""
    raw = Decimal(base) * (Decimal(100) + Decimal(str(markup_pct or 0))) / Decimal(100)
    return int((raw / 100).to_integral_value(ROUND_CEILING)) * 100


async def catalog() -> list[dict]:
    s = await get_settings()
    rows = await pool.fetch("SELECT * FROM products WHERE active ORDER BY category, sort, id")
    return [{"id": r["id"], "category": r["category"], "title": r["title"], "emoji": r["emoji"],
             "price": final_price(r["base_price"], s.get(f"markup_{r['category']}")),
             "enabled": s.get(f"enabled_{r['category']}") == "1"} for r in rows]


# ---------- пользователи / баланс ----------
async def upsert_user(tg_id: int, username: str | None, first_name: str | None):
    await pool.execute(
        "INSERT INTO users(tg_id,username,first_name) VALUES($1,$2,$3) "
        "ON CONFLICT(tg_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name",
        tg_id, username, first_name)


async def get_balance(tg_id: int) -> int:
    return await pool.fetchval("SELECT balance FROM users WHERE tg_id=$1", tg_id) or 0


async def _apply(conn, user_id: int, delta: int, reason: str, ref: str | None = None) -> int:
    """Изменение баланса. Строка пользователя блокируется FOR UPDATE до конца транзакции."""
    bal = await conn.fetchval("SELECT balance FROM users WHERE tg_id=$1 FOR UPDATE", user_id)
    if bal is None:
        raise BotError("no_user", "Пользователь не найден")
    if bal + delta < 0:
        raise BotError("insufficient", "Недостаточно средств")
    await conn.execute("UPDATE users SET balance=$2 WHERE tg_id=$1", user_id, bal + delta)
    await conn.execute("INSERT INTO balance_log(user_id,delta,balance_after,reason,ref) VALUES($1,$2,$3,$4,$5)",
                       user_id, delta, bal + delta, reason, ref)
    return bal + delta


async def manual_credit(user_id: int, delta: int, reason: str = "manual") -> int:
    async with pool.acquire() as conn, conn.transaction():
        return await _apply(conn, user_id, delta, reason)


# ---------- пополнения ----------
async def create_topup(user_id: int, amount: int, method: str):
    ttl = int(await get_setting("topup_ttl_min") or 20)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE topups SET status='expired' WHERE status='pending' AND expires_at < now()")
        await conn.execute("UPDATE topups SET status='expired' WHERE status='pending' AND user_id=$1", user_id)
        for offset in range(100):            # уникализируем сумму: +0..99 сум
            try:
                return await conn.fetchrow(
                    "INSERT INTO topups(user_id,amount,base_amount,method,expires_at) "
                    "VALUES($1,$2,$3,$4, now() + make_interval(mins => $5)) RETURNING *",
                    user_id, amount + offset, amount, method, ttl)
            except asyncpg.UniqueViolationError:
                continue
    raise BotError("busy", "Сейчас много платежей, попробуйте через пару минут")


async def match_payment(amount: int, event_hash: str, raw: str):
    """Входящее поступление от парсера. Возвращает ('matched'|'unmatched'|'duplicate', topup)."""
    async with pool.acquire() as conn, conn.transaction():
        res = await conn.execute("INSERT INTO bank_events(hash,raw,amount) VALUES($1,$2,$3) "
                                 "ON CONFLICT DO NOTHING", event_hash, raw, amount)
        if res.endswith(" 0"):
            return "duplicate", None
        t = await conn.fetchrow("SELECT * FROM topups WHERE status='pending' AND amount=$1 "
                                "AND expires_at > now() FOR UPDATE", amount)
        if not t:
            return "unmatched", None
        await conn.execute("UPDATE topups SET status='paid', paid_at=now(), source='bank' WHERE id=$1", t["id"])
        bal = await _apply(conn, t["user_id"], t["amount"], "topup", f"topup:{t['id']}")
        await conn.execute("UPDATE bank_events SET matched_topup=$2 WHERE hash=$1", event_hash, t["id"])
        return "matched", {**dict(t), "balance": bal}


async def resolve_topup(topup_id: int, approve: bool):
    """Ручное подтверждение/отклонение админом."""
    async with pool.acquire() as conn, conn.transaction():
        t = await conn.fetchrow("SELECT * FROM topups WHERE id=$1 FOR UPDATE", topup_id)
        if not t:
            raise BotError("not_found", "Пополнение не найдено")
        if t["status"] == "paid":
            raise BotError("done", "Уже зачислено")
        if approve:
            await conn.execute("UPDATE topups SET status='paid', paid_at=now(), source='admin' WHERE id=$1", topup_id)
            bal = await _apply(conn, t["user_id"], t["amount"], "topup_manual", f"topup:{topup_id}")
            return {**dict(t), "balance": bal}
        await conn.execute("UPDATE topups SET status='rejected' WHERE id=$1", topup_id)
        return dict(t)


# ---------- заказы ----------
async def purchase(user_id: int, product_id: int, recipient: str):
    async with pool.acquire() as conn, conn.transaction():
        p = await conn.fetchrow("SELECT * FROM products WHERE id=$1 AND active", product_id)
        if not p:
            raise BotError("not_found", "Товар не найден")
        cat = p["category"]
        if await conn.fetchval("SELECT value FROM settings WHERE key=$1", f"enabled_{cat}") != "1":
            raise BotError("service_disabled", SERVICE_DISABLED)
        markup = await conn.fetchval("SELECT value FROM settings WHERE key=$1", f"markup_{cat}")
        price = final_price(p["base_price"], markup)
        order = await conn.fetchrow(
            "INSERT INTO orders(user_id,product_id,category,title,price,recipient) "
            "VALUES($1,$2,$3,$4,$5,$6) RETURNING *", user_id, product_id, cat, p["title"], price, recipient)
        bal = await _apply(conn, user_id, -price, "purchase", f"order:{order['id']}")
        return dict(order), bal


async def order_action(order_id: int, action: str):
    """action: 'done' — выдан; 'refund' — отклонить и вернуть деньги."""
    async with pool.acquire() as conn, conn.transaction():
        o = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
        if not o:
            raise BotError("not_found", "Заказ не найден")
        if o["status"] != "processing":
            raise BotError("done", f"Заказ уже в статусе «{o['status']}»")
        if action == "done":
            await conn.execute("UPDATE orders SET status='done', updated_at=now() WHERE id=$1", order_id)
        else:
            await conn.execute("UPDATE orders SET status='refunded', updated_at=now() WHERE id=$1", order_id)
            await _apply(conn, o["user_id"], o["price"], "refund", f"order:{order_id}")
        return dict(o)
