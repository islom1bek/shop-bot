#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram shop bot - single-file edition (Python 3.12, aiogram 3.x, PostgreSQL, SQLAlchemy 2 async).

All customer/admin-facing text is Russian. Code, comments and docs are English.
The database schema is created/updated automatically on start (idempotent), see SCHEMA below.

Run:  python bot.py          (configuration comes from environment variables or a .env file)
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import logging.handlers
import os
import re
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import (TelegramAPIError, TelegramBadRequest, TelegramForbiddenError,
                                TelegramRetryAfter)
from aiogram.filters import BaseFilter, Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
                           KeyboardButton, Message, ReplyKeyboardMarkup, TelegramObject)
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

log = logging.getLogger("shopbot")

# =====================================================================================
# 1. CONFIGURATION
# =====================================================================================


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    tz_name: str
    log_level: str
    log_file: str
    currency: str
    deadline_min: int
    sweep_sec: int
    max_admins: int
    receipt_max_bytes: int
    backup_dir: str


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config() -> Config:
    _load_dotenv()
    errs: list[str] = []

    def get(name: str, default: str | None = None, required: bool = False) -> str:
        v = os.environ.get(name, default)
        if v is None or str(v).strip() == "":
            if required:
                errs.append(f"{name} is required")
            return ""
        return str(v).strip()

    def geti(name: str, default: int, lo: int, hi: int) -> int:
        raw = get(name, str(default))
        try:
            val = int(raw)
        except ValueError:
            errs.append(f"{name} must be an integer")
            return default
        if not lo <= val <= hi:
            errs.append(f"{name} must be between {lo} and {hi}")
        return val

    token = get("BOT_TOKEN", required=True)
    if token and not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", token):
        errs.append("BOT_TOKEN has an invalid format (expected '<digits>:<secret>')")
    owner_raw = get("OWNER_TELEGRAM_ID", required=True)
    owner = 0
    if owner_raw:
        if owner_raw.isdigit() and int(owner_raw) > 0:
            owner = int(owner_raw)
        else:
            errs.append("OWNER_TELEGRAM_ID must be a positive numeric Telegram user ID (not a username)")
    tz_name = get("APP_TIMEZONE", "Asia/Tashkent")
    try:
        ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        errs.append(f"APP_TIMEZONE '{tz_name}' is not a valid IANA timezone")
    level = get("LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errs.append("LOG_LEVEL must be DEBUG/INFO/WARNING/ERROR/CRITICAL")
    cfg = Config(
        bot_token=token, owner_id=owner,
        pg_host=get("POSTGRES_HOST", "db"), pg_port=geti("POSTGRES_PORT", 5432, 1, 65535),
        pg_db=get("POSTGRES_DB", "shopbot"), pg_user=get("POSTGRES_USER", "shopbot"),
        pg_password=get("POSTGRES_PASSWORD", required=True),
        tz_name=tz_name, log_level=level, log_file=get("LOG_FILE", ""),
        currency=get("DEFAULT_CURRENCY", "USD")[:8] or "USD",
        deadline_min=geti("PAYMENT_DEADLINE_MINUTES", 10, 1, 1440),
        sweep_sec=geti("DEADLINE_SWEEP_INTERVAL_SECONDS", 15, 1, 300),
        max_admins=geti("MAX_ADMINS", 3, 0, 3),
        receipt_max_bytes=geti("RECEIPT_MAX_BYTES", 10 * 1024 * 1024, 1024, 50 * 1024 * 1024),
        backup_dir=get("BACKUP_DIR", "/backups"),
    )
    if errs:
        raise ConfigError("; ".join(errs))
    return cfg


CFG: Config = None  # type: ignore[assignment]
TZ: ZoneInfo = ZoneInfo("UTC")
ENGINE = None
SF: async_sessionmaker | None = None
START_TS = time.time()
HEARTBEAT: dict[str, float] = {}
ERRORS: deque = deque(maxlen=10)


def init_config(cfg: Config) -> None:
    global CFG, TZ
    CFG = cfg
    TZ = ZoneInfo(cfg.tz_name)


# ------------------------------------- logging ---------------------------------------


class RedactFilter(logging.Filter):
    """Removes the bot token and DB password from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            for secret in (getattr(CFG, "bot_token", ""), getattr(CFG, "pg_password", "")):
                if secret:
                    msg = msg.replace(secret, "***")
            msg = re.sub(r"bot\d{5,}:[A-Za-z0-9_-]{20,}", "bot***", msg)
            record.msg, record.args = msg, ()
        except Exception:  # never break logging
            pass
        return True


class RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            ERRORS.append((datetime.now(timezone.utc), record.levelname, record.getMessage()[:300]))


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(CFG.log_level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if CFG.log_file:
        Path(CFG.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(CFG.log_file, maxBytes=5_000_000, backupCount=5,
                                                              encoding="utf-8"))
    handlers.append(RingHandler())
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactFilter())
        root.addHandler(h)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


# =====================================================================================
# 2. SMALL HELPERS / RUSSIAN LABELS
# =====================================================================================

e = html.escape
STAFF = ("owner", "admin")

STATUS_RU = {
    "AWAITING_PAYMENT": "Ожидает оплаты", "PAYMENT_REVIEW": "Чек на проверке",
    "PAYMENT_REJECTED": "Оплата отклонена", "PAID": "Оплачен", "PROCESSING": "В обработке",
    "DISPATCHED": "Отправлен, готов к получению", "REJECTED_BEFORE_PAYMENT": "Отклонён",
    "CANCELLED_BY_CUSTOMER": "Отменён клиентом", "CANCELLED_PAYMENT_TIMEOUT": "Отменён: время оплаты истекло",
}
PAY_STATUS_RU = {
    "NOT_STARTED": "Не начата", "AWAITING_RECEIPT": "Ожидается чек", "UNDER_REVIEW": "На проверке",
    "REJECTED": "Отклонена", "CONFIRMED": "Подтверждена",
}
METHOD_RU = {"USDT_TRC20": "USDT (TRC20)", "CARD": "Банковская карта"}
FINAL = {"DISPATCHED", "REJECTED_BEFORE_PAYMENT", "CANCELLED_BY_CUSTOMER", "CANCELLED_PAYMENT_TIMEOUT"}
OPEN_UNPAID = ("AWAITING_PAYMENT", "PAYMENT_REVIEW", "PAYMENT_REJECTED")
CARD_OFF_TEXT = "Этот способ оплаты временно недоступен. Ведутся технические работы."
ERR_TEXT = "Произошла ошибка. Пожалуйста, попробуйте ещё раз чуть позже."
NO_RIGHTS = "Недостаточно прав для этого действия."


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fmt_dt(dt: datetime | None) -> str:
    return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M") if dt else "—"


def money(v, cur: str | None = None) -> str:
    d = Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{d:,.2f}".replace(",", " ") + f" {cur or CFG.currency}"


def attrs_text(attrs) -> str:
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    return "; ".join(f"{e(str(k))}: {e(str(v))}" for k, v in (attrs or {}).items()) or "—"


def user_link(u: dict) -> str:
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or "Клиент"
    uname = f" @{e(u['username'])}" if u.get("username") else ""
    return f'<a href="tg://user?id={u["tg_id"]}">{e(name)}</a>{uname} (ID: <code>{u["tg_id"]}</code>)'


def jl(v):
    """asyncpg returns JSONB from raw SQL as text; normalise to Python objects."""
    return json.loads(v) if isinstance(v, (str, bytes)) else (v if v is not None else {})


def trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# =====================================================================================
# 3. DATABASE: SCHEMA + HELPERS
# =====================================================================================

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users(
        id BIGSERIAL PRIMARY KEY, telegram_id BIGINT NOT NULL UNIQUE, username TEXT, first_name TEXT, last_name TEXT,
        is_bot_blocked BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at TIMESTAMPTZ)""",
    """CREATE TABLE IF NOT EXISTS agreement_versions(
        id BIGSERIAL PRIMARY KEY, version INT NOT NULL UNIQUE, file_id TEXT NOT NULL, file_unique_id TEXT,
        file_name TEXT, file_size INT, is_current BOOLEAN NOT NULL DEFAULT false, published_by BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_agreement_current ON agreement_versions(is_current) WHERE is_current",
    """CREATE TABLE IF NOT EXISTS agreement_acceptances(
        id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
        agreement_version_id BIGINT NOT NULL REFERENCES agreement_versions(id),
        accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id, agreement_version_id))""",
    """CREATE TABLE IF NOT EXISTS cities(
        id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT true, pickup_name TEXT,
        pickup_address TEXT, pickup_instructions TEXT, map_url TEXT, contact_info TEXT, working_hours TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_name ON cities(lower(name))",
    """CREATE TABLE IF NOT EXISTS products(
        id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, description TEXT, is_active BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS product_cities(
        product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        city_id BIGINT NOT NULL REFERENCES cities(id) ON DELETE CASCADE, PRIMARY KEY(product_id, city_id))""",
    """CREATE TABLE IF NOT EXISTS product_images(
        id BIGSERIAL PRIMARY KEY, product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        file_id TEXT NOT NULL, position INT NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS product_variants(
        id BIGSERIAL PRIMARY KEY, product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        attrs JSONB NOT NULL DEFAULT '{}', price NUMERIC(12,2) NOT NULL CHECK (price >= 0),
        is_active BOOLEAN NOT NULL DEFAULT true, position INT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS orders(
        id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
        city_id BIGINT REFERENCES cities(id) ON DELETE SET NULL,
        variant_id BIGINT REFERENCES product_variants(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'AWAITING_PAYMENT' CHECK (status IN ('AWAITING_PAYMENT','PAYMENT_REVIEW',
          'PAYMENT_REJECTED','PAID','PROCESSING','DISPATCHED','REJECTED_BEFORE_PAYMENT','CANCELLED_BY_CUSTOMER',
          'CANCELLED_PAYMENT_TIMEOUT')),
        payment_status TEXT NOT NULL DEFAULT 'AWAITING_RECEIPT' CHECK (payment_status IN ('NOT_STARTED',
          'AWAITING_RECEIPT','UNDER_REVIEW','REJECTED','CONFIRMED')),
        payment_method TEXT CHECK (payment_method IN ('USDT_TRC20','CARD')),
        total_price NUMERIC(12,2) NOT NULL CHECK (total_price >= 0), currency TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE, payment_deadline_at TIMESTAMPTZ,
        assigned_to BIGINT, assigned_at TIMESTAMPTZ, cancel_reason TEXT, cancelled_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_one_open ON orders(user_id)
        WHERE status IN ('AWAITING_PAYMENT','PAYMENT_REVIEW','PAYMENT_REJECTED')""",
    """CREATE INDEX IF NOT EXISTS ix_orders_deadline ON orders(payment_deadline_at)
        WHERE status IN ('AWAITING_PAYMENT','PAYMENT_REJECTED')""",
    "CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status)",
    "CREATE INDEX IF NOT EXISTS ix_orders_assigned ON orders(assigned_to)",
    "CREATE INDEX IF NOT EXISTS ix_orders_city ON orders(city_id)",
    """CREATE TABLE IF NOT EXISTS order_items(
        id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
        variant_id BIGINT REFERENCES product_variants(id) ON DELETE SET NULL,
        product_name TEXT NOT NULL, attrs JSONB NOT NULL DEFAULT '{}', image_file_id TEXT, city_name TEXT NOT NULL,
        pickup JSONB NOT NULL DEFAULT '{}', unit_price NUMERIC(12,2) NOT NULL, currency TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id)",
    """CREATE TABLE IF NOT EXISTS order_status_history(
        id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        from_status TEXT, to_status TEXT NOT NULL, from_pay TEXT, to_pay TEXT, actor BIGINT, reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS ix_osh_order ON order_status_history(order_id)",
    """CREATE TABLE IF NOT EXISTS order_assignments(
        id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        admin_id BIGINT NOT NULL, assigned_by BIGINT NOT NULL, assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        released_at TIMESTAMPTZ)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assign_active ON order_assignments(order_id) WHERE released_at IS NULL",
    """CREATE TABLE IF NOT EXISTS payments(
        id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        method TEXT NOT NULL CHECK (method IN ('USDT_TRC20','CARD')),
        status TEXT NOT NULL CHECK (status IN ('AWAITING_RECEIPT','UNDER_REVIEW','REJECTED','CONFIRMED','CANCELLED')),
        amount NUMERIC(12,2) NOT NULL, currency TEXT NOT NULL, wallet_snapshot TEXT, decided_by BIGINT,
        decided_at TIMESTAMPTZ, decision_reason TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_open ON payments(order_id)
        WHERE status IN ('AWAITING_RECEIPT','UNDER_REVIEW')""",
    """CREATE TABLE IF NOT EXISTS receipts(
        id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        payment_id BIGINT NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('PHOTO','PDF')), file_id TEXT NOT NULL, file_unique_id TEXT,
        mime_type TEXT, file_size INT, status TEXT NOT NULL DEFAULT 'SUBMITTED'
          CHECK (status IN ('SUBMITTED','APPROVED','REJECTED')),
        submitted_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS ix_receipts_order ON receipts(order_id)",
    """CREATE TABLE IF NOT EXISTS order_dispatches(
        id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        photo_file_id TEXT NOT NULL, ready_at TIMESTAMPTZ NOT NULL, pickup_info TEXT NOT NULL, extra_message TEXT,
        sent_by BIGINT NOT NULL, sent_at TIMESTAMPTZ, failed_note TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS ix_dispatch_order ON order_dispatches(order_id)",
    """CREATE TABLE IF NOT EXISTS support_conversations(
        id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
        status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')), assigned_to BIGINT,
        assigned_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), closed_at TIMESTAMPTZ,
        last_message_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_support_open ON support_conversations(user_id) WHERE status = 'OPEN'",
    """CREATE TABLE IF NOT EXISTS support_messages(
        id BIGSERIAL PRIMARY KEY, conversation_id BIGINT NOT NULL REFERENCES support_conversations(id) ON DELETE CASCADE,
        sender_role TEXT NOT NULL CHECK (sender_role IN ('CUSTOMER','STAFF')), sender_id BIGINT NOT NULL,
        body TEXT, media_type TEXT, media_file_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS ix_support_msg_conv ON support_messages(conversation_id)",
    """CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by BIGINT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS admins(
        id BIGSERIAL PRIMARY KEY, telegram_id BIGINT NOT NULL UNIQUE, is_active BOOLEAN NOT NULL DEFAULT true,
        added_by BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), removed_at TIMESTAMPTZ)""",
    """CREATE TABLE IF NOT EXISTS audit_logs(
        id BIGSERIAL PRIMARY KEY, actor BIGINT, action TEXT NOT NULL, entity_type TEXT, entity_id TEXT,
        details JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_logs(actor, action)",
    """CREATE TABLE IF NOT EXISTS outbox(
        id BIGSERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, kind TEXT NOT NULL, payload JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SENT','FAILED')),
        attempts INT NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_error TEXT,
        dedupe_key TEXT UNIQUE, hook TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), sent_at TIMESTAMPTZ)""",
    "CREATE INDEX IF NOT EXISTS ix_outbox_due ON outbox(next_attempt_at) WHERE status = 'PENDING'",
    """CREATE TABLE IF NOT EXISTS broadcasts(
        id BIGSERIAL PRIMARY KEY, created_by BIGINT NOT NULL, body TEXT NOT NULL, photo_file_id TEXT,
        status TEXT NOT NULL DEFAULT 'SENDING' CHECK (status IN ('SENDING','FINISHED')),
        total INT NOT NULL DEFAULT 0, sent INT NOT NULL DEFAULT 0, failed INT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ)""",
    """CREATE TABLE IF NOT EXISTS broadcast_deliveries(
        id BIGSERIAL PRIMARY KEY, broadcast_id BIGINT NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SENT','BLOCKED','FAILED')),
        error TEXT, sent_at TIMESTAMPTZ, UNIQUE(broadcast_id, user_id))""",
    # ---- database-level guards ----
    """CREATE OR REPLACE FUNCTION enforce_max_admins() RETURNS trigger AS $$
        BEGIN
          IF NEW.is_active THEN
            PERFORM pg_advisory_xact_lock(727001);
            IF (SELECT count(*) FROM admins WHERE is_active AND id IS DISTINCT FROM NEW.id) >= 3 THEN
              RAISE EXCEPTION 'max_admins_exceeded' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS trg_admins_max ON admins",
    """CREATE TRIGGER trg_admins_max BEFORE INSERT OR UPDATE OF is_active ON admins
        FOR EACH ROW EXECUTE FUNCTION enforce_max_admins()""",
    """CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'audit_logs is append-only' USING ERRCODE = '42501'; END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_logs",
    """CREATE TRIGGER trg_audit_immutable BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable()""",
    """CREATE OR REPLACE FUNCTION order_items_immutable() RETURNS trigger AS $$
        BEGIN
          IF NEW.product_name IS DISTINCT FROM OLD.product_name OR NEW.attrs IS DISTINCT FROM OLD.attrs
             OR NEW.city_name IS DISTINCT FROM OLD.city_name OR NEW.pickup IS DISTINCT FROM OLD.pickup
             OR NEW.unit_price IS DISTINCT FROM OLD.unit_price OR NEW.currency IS DISTINCT FROM OLD.currency THEN
            RAISE EXCEPTION 'order_items snapshot is immutable' USING ERRCODE = '42501';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS trg_order_items_immutable ON order_items",
    """CREATE TRIGGER trg_order_items_immutable BEFORE UPDATE ON order_items
        FOR EACH ROW EXECUTE FUNCTION order_items_immutable()""",
]

DEFAULT_SETTINGS = {"card_enabled": "0", "usdt_wallet": "", "usdt_instructions": "", "card_instructions": "",
                    "payment_help_text": ""}


async def init_db() -> None:
    global ENGINE, SF
    url = URL.create("postgresql+asyncpg", username=CFG.pg_user, password=CFG.pg_password, host=CFG.pg_host,
                     port=CFG.pg_port, database=CFG.pg_db)
    ENGINE = create_async_engine(url, pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=1800,
                                 connect_args={"server_settings": {"timezone": "UTC"}})
    SF = async_sessionmaker(ENGINE, expire_on_commit=False)
    async with ENGINE.connect() as c:  # fail fast with a clear error
        await c.execute(text("SELECT 1"))


async def ensure_schema() -> None:
    async with ENGINE.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(727000)"))
        for stmt in SCHEMA:
            await conn.execute(text(stmt))
        for k, v in DEFAULT_SETTINGS.items():
            await conn.execute(text("INSERT INTO settings(key,value) VALUES(:k,:v) ON CONFLICT (key) DO NOTHING"),
                               {"k": k, "v": v})


@asynccontextmanager
async def tx():
    """One transaction: commit on success, rollback on error."""
    async with SF() as s:
        async with s.begin():
            yield s


async def q_all(s, sql: str, **p) -> list[dict]:
    return [dict(r) for r in (await s.execute(text(sql), p)).mappings()]


async def q_one(s, sql: str, **p) -> dict | None:
    r = (await s.execute(text(sql), p)).mappings().first()
    return dict(r) if r else None


async def q_exec(s, sql: str, **p) -> int:
    return (await s.execute(text(sql), p)).rowcount


async def fetchall(sql: str, **p) -> list[dict]:
    async with SF() as s:
        return await q_all(s, sql, **p)


async def fetchone(sql: str, **p) -> dict | None:
    async with SF() as s:
        return await q_one(s, sql, **p)


async def audit(s, actor: int | None, action: str, etype: str | None = None, eid=None, **details) -> None:
    await q_exec(s, "INSERT INTO audit_logs(actor,action,entity_type,entity_id,details) "
                    "VALUES(:a,:ac,:et,:ei,CAST(:d AS JSONB))",
                 a=actor, ac=action, et=etype, ei=None if eid is None else str(eid),
                 d=json.dumps(details, ensure_ascii=False, default=str))


async def get_setting(key: str, s=None) -> str:
    sql, p = "SELECT value FROM settings WHERE key=:k", {"k": key}
    r = await q_one(s, sql, **p) if s else await fetchone(sql, **p)
    return r["value"] if r else ""


async def set_setting(s, key: str, value: str, actor: int) -> None:
    await q_exec(s, "INSERT INTO settings(key,value,updated_by,updated_at) VALUES(:k,:v,:a,now()) "
                    "ON CONFLICT (key) DO UPDATE SET value=:v, updated_by=:a, updated_at=now()",
                 k=key, v=value, a=actor)


# ------------------------------------- roles -----------------------------------------


async def get_role(tg_id: int) -> str:
    if tg_id == CFG.owner_id:
        return "owner"
    r = await fetchone("SELECT 1 AS x FROM admins WHERE telegram_id=:t AND is_active", t=tg_id)
    return "admin" if r else "customer"


async def staff_ids(s) -> list[int]:
    rows = await q_all(s, "SELECT telegram_id FROM admins WHERE is_active")
    return [CFG.owner_id] + [r["telegram_id"] for r in rows if r["telegram_id"] != CFG.owner_id]


# ------------------------------------- outbox ----------------------------------------


def _kb_payload(buttons) -> list | None:
    return [[[t, d] for t, d in row] for row in buttons] if buttons else None


async def outbox_add(s, chat_id: int, kind: str = "text", *, body: str = "", file_id: str | None = None,
                     buttons=None, dedupe: str | None = None, hook: str | None = None) -> None:
    payload = {"text": body, "file_id": file_id, "buttons": _kb_payload(buttons)}
    await q_exec(s, "INSERT INTO outbox(chat_id,kind,payload,dedupe_key,hook) VALUES(:c,:k,CAST(:p AS JSONB),:d,:h) "
                    "ON CONFLICT (dedupe_key) DO NOTHING",
                 c=chat_id, k=kind, p=json.dumps(payload, ensure_ascii=False), d=dedupe, h=hook)


async def notify_staff(s, body: str, buttons=None, only: list[int] | None = None) -> None:
    for tid in (only if only is not None else await staff_ids(s)):
        await outbox_add(s, tid, "text", body=body, buttons=buttons)


async def notify_responsible(s, o: dict, body: str, buttons=None, exclude: int | None = None) -> None:
    """Assigned admin + owner (or all staff while the order is unassigned)."""
    if o.get("assigned_to"):
        ids = list({CFG.owner_id, o["assigned_to"]})
    else:
        ids = await staff_ids(s)
    await notify_staff(s, body, buttons, only=[i for i in ids if i != exclude])


# =====================================================================================
# 4. BUSINESS SERVICES (state machine, orders, payments, support)
# =====================================================================================


class Illegal(Exception):
    """Raised when an order state transition is not allowed."""


LEGAL = {
    ("AWAITING_PAYMENT", "PAYMENT_REVIEW"), ("AWAITING_PAYMENT", "CANCELLED_BY_CUSTOMER"),
    ("AWAITING_PAYMENT", "CANCELLED_PAYMENT_TIMEOUT"), ("AWAITING_PAYMENT", "REJECTED_BEFORE_PAYMENT"),
    ("PAYMENT_REVIEW", "PAID"), ("PAYMENT_REVIEW", "PAYMENT_REJECTED"),
    ("PAYMENT_REJECTED", "PAYMENT_REVIEW"), ("PAYMENT_REJECTED", "CANCELLED_BY_CUSTOMER"),
    ("PAYMENT_REJECTED", "CANCELLED_PAYMENT_TIMEOUT"), ("PAYMENT_REJECTED", "REJECTED_BEFORE_PAYMENT"),
    ("PAID", "PROCESSING"), ("PROCESSING", "DISPATCHED"),
}
_KEEP = object()


async def transition(s, oid: int, to: str, *, pay: str | None = None, actor: int | None = None,
                     reason: str | None = None, deadline=_KEEP) -> str:
    """Atomic, validated state change. Locks the order row; raises Illegal on any invalid transition."""
    row = await q_one(s, "SELECT status, payment_status FROM orders WHERE id=:i FOR UPDATE", i=oid)
    if row is None:
        raise Illegal("not_found")
    frm = row["status"]
    if (frm, to) not in LEGAL:
        raise Illegal(f"{frm}->{to}")
    sets, p = ["status=:to", "updated_at=now()"], {"i": oid, "to": to}
    if pay:
        sets.append("payment_status=:pay")
        p["pay"] = pay
    if to.startswith("CANCELLED") or to == "REJECTED_BEFORE_PAYMENT":
        sets += ["cancelled_at=now()", "cancel_reason=:rs", "payment_deadline_at=NULL"]
        p["rs"] = reason
    elif deadline is None:
        sets.append("payment_deadline_at=NULL")
    elif deadline is not _KEEP:
        sets.append("payment_deadline_at=:dl")
        p["dl"] = deadline
    await q_exec(s, f"UPDATE orders SET {', '.join(sets)} WHERE id=:i", **p)
    await q_exec(s, "INSERT INTO order_status_history(order_id,from_status,to_status,from_pay,to_pay,actor,reason) "
                    "VALUES(:i,:f,:t,:fp,:tp,:a,:r)",
                 i=oid, f=frm, t=to, fp=row["payment_status"], tp=pay or row["payment_status"], a=actor, r=reason)
    return frm


_ORDER_SQL = """SELECT o.id, o.user_id, o.city_id, o.status, o.payment_status, o.payment_method, o.total_price,
    o.currency, o.payment_deadline_at, o.assigned_to, o.assigned_at, o.cancel_reason, o.created_at,
    i.product_name, i.attrs, i.image_file_id, i.city_name, i.pickup, i.unit_price,
    u.telegram_id AS tg_id, u.username, u.first_name, u.last_name
    FROM orders o JOIN order_items i ON i.order_id=o.id JOIN users u ON u.id=o.user_id WHERE o.id=:i"""


async def load_order(s, oid: int, lock: bool = False) -> dict | None:
    o = await q_one(s, _ORDER_SQL + (" FOR UPDATE OF o" if lock else ""), i=oid)
    if o:
        o["attrs"], o["pickup"] = jl(o["attrs"]), jl(o["pickup"])
    return o


def authorized(o: dict, actor: int, role: str) -> bool:
    return role == "owner" or (role == "admin" and o.get("assigned_to") == actor)


def staff_card(o: dict, history: list[dict] | None = None, dispatch: dict | None = None) -> str:
    lines = [
        "📦 <b>Заказ</b>",
        f"Клиент: {user_link(o)}",
        f"Товар: <b>{e(o['product_name'])}</b>",
        f"Вариант: {attrs_text(o['attrs'])}",
        f"Город: {e(o['city_name'])}",
        f"Цена: <b>{money(o['total_price'], o['currency'])}</b>",
        f"Статус: {STATUS_RU[o['status']]}",
        f"Оплата: {PAY_STATUS_RU[o['payment_status']]}"
        + (f" ({METHOD_RU[o['payment_method']]})" if o.get("payment_method") else ""),
        f"Создан: {fmt_dt(o['created_at'])}",
        f"Ответственный: {('<code>%s</code>' % o['assigned_to']) if o.get('assigned_to') else 'не назначен'}",
    ]
    if o["status"] in ("AWAITING_PAYMENT", "PAYMENT_REJECTED") and o.get("payment_deadline_at"):
        lines.append(f"Срок оплаты до: {fmt_dt(o['payment_deadline_at'])}")
    if o.get("cancel_reason"):
        lines.append(f"Причина: {e(o['cancel_reason'])}")
    if dispatch:
        lines.append(f"Готов к выдаче: {fmt_dt(dispatch['ready_at'])}"
                     + ("" if dispatch.get("sent_at") else " (уведомление не доставлено)"))
    if history:
        lines.append("\n<b>История:</b>")
        for h in history[-8:]:
            who = f" [{h['actor']}]" if h.get("actor") else " [система]"
            why = f" — {e(h['reason'])}" if h.get("reason") else ""
            lines.append(f"{fmt_dt(h['created_at'])}: {STATUS_RU.get(h['from_status'], '∅')} → "
                         f"{STATUS_RU[h['to_status']]}{who}{why}")
    return "\n".join(lines)


def customer_card(o: dict, dispatch: dict | None = None) -> str:
    lines = [
        f"<b>{e(o['product_name'])}</b>",
        f"Вариант: {attrs_text(o['attrs'])}",
        f"Город: {e(o['city_name'])}",
        f"Цена: {money(o['total_price'], o['currency'])}",
        f"Статус заказа: <b>{STATUS_RU[o['status']]}</b>",
        f"Статус оплаты: {PAY_STATUS_RU[o['payment_status']] if o['status'] not in FINAL or o['status']=='DISPATCHED' else '—'}",
        f"Создан: {fmt_dt(o['created_at'])}",
    ]
    if o["status"] in ("AWAITING_PAYMENT", "PAYMENT_REJECTED") and o.get("payment_deadline_at"):
        lines.append(f"Оплатить до: {fmt_dt(o['payment_deadline_at'])}")
    if o["status"] in ("CANCELLED_BY_CUSTOMER", "CANCELLED_PAYMENT_TIMEOUT", "REJECTED_BEFORE_PAYMENT") \
            and o.get("cancel_reason"):
        lines.append(f"Причина: {e(o['cancel_reason'])}")
    if dispatch and dispatch.get("sent_at"):
        lines.append(f"\n<b>Получение:</b> {fmt_dt(dispatch['ready_at'])}\n{e(dispatch['pickup_info'])}"
                     + (f"\n{e(dispatch['extra_message'])}" if dispatch.get("extra_message") else ""))
    return "\n".join(lines)


# ------------------------------------- catalog ---------------------------------------


async def list_active_cities() -> list[dict]:
    return await fetchall("SELECT id, name FROM cities WHERE is_active ORDER BY name")


async def list_city_products(city_id: int) -> list[dict]:
    return await fetchall(
        """SELECT p.id, p.name, MIN(v.price) AS min_price FROM products p
           JOIN product_cities pc ON pc.product_id=p.id AND pc.city_id=:c
           JOIN cities c ON c.id=pc.city_id AND c.is_active
           JOIN product_variants v ON v.product_id=p.id AND v.is_active
           WHERE p.is_active GROUP BY p.id, p.name ORDER BY p.name""", c=city_id)


async def get_product_for_city(pid: int, city_id: int) -> dict | None:
    async with SF() as s:
        p = await q_one(s, """SELECT p.id, p.name, p.description FROM products p
            JOIN product_cities pc ON pc.product_id=p.id AND pc.city_id=:c
            JOIN cities c ON c.id=pc.city_id AND c.is_active WHERE p.id=:p AND p.is_active""", p=pid, c=city_id)
        if not p:
            return None
        p["variants"] = await q_all(s, "SELECT id, attrs, price FROM product_variants WHERE product_id=:p AND is_active "
                                       "ORDER BY position, id", p=pid)
        for v in p["variants"]:
            v["attrs"] = jl(v["attrs"])
        p["images"] = [r["file_id"] for r in await q_all(
            s, "SELECT file_id FROM product_images WHERE product_id=:p ORDER BY position, id", p=pid)]
        return p


# ------------------------------------- orders ----------------------------------------


async def upsert_user(u) -> dict:
    return await _upsert_user(u.id, u.username, u.first_name, u.last_name)


async def _upsert_user(tg_id, username, first, last) -> dict:
    async with tx() as s:
        return await q_one(
            s, """INSERT INTO users(telegram_id,username,first_name,last_name,last_seen_at,is_bot_blocked)
                  VALUES(:t,:u,:f,:l,now(),false)
                  ON CONFLICT (telegram_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name,
                    last_name=EXCLUDED.last_name, last_seen_at=now(), is_bot_blocked=false
                  RETURNING id, telegram_id, username, first_name, last_name""",
            t=tg_id, u=username, f=first, l=last)


async def current_agreement() -> dict | None:
    return await fetchone("SELECT id, version, file_id, file_name, created_at FROM agreement_versions WHERE is_current")


async def has_accepted(user_id: int, agreement_id: int) -> bool:
    return bool(await fetchone("SELECT 1 AS x FROM agreement_acceptances WHERE user_id=:u AND agreement_version_id=:a",
                               u=user_id, a=agreement_id))


async def accept_agreement(user: dict, version: int) -> str:
    async with tx() as s:
        ag = await q_one(s, "SELECT id, version FROM agreement_versions WHERE is_current")
        if not ag or ag["version"] != version:
            return "outdated"
        n = await q_exec(s, "INSERT INTO agreement_acceptances(user_id, agreement_version_id) VALUES(:u,:a) "
                            "ON CONFLICT DO NOTHING", u=user["id"], a=ag["id"])
        if n:
            await audit(s, user["telegram_id"], "agreement_accepted", "agreement", ag["id"], version=ag["version"])
        return "ok"


async def create_order(user: dict, city_id: int, variant_id: int, token: str) -> tuple[str, int | None]:
    """Creates the order with an immutable snapshot. Idempotent per (user, city, variant, token)."""
    key = f"{user['id']}:{city_id}:{variant_id}:{token}"
    async with tx() as s:
        ex = await q_one(s, "SELECT id FROM orders WHERE idempotency_key=:k", k=key)
        if ex:
            return "dup", ex["id"]
        v = await q_one(s, """SELECT v.id AS vid, v.price, v.attrs, p.id AS pid, p.name AS pname, c.id AS cid,
                c.name AS cname, c.pickup_name, c.pickup_address, c.pickup_instructions, c.map_url, c.contact_info,
                c.working_hours,
                (SELECT file_id FROM product_images WHERE product_id=p.id ORDER BY position, id LIMIT 1) AS img
            FROM product_variants v JOIN products p ON p.id=v.product_id
            JOIN product_cities pc ON pc.product_id=p.id AND pc.city_id=:c JOIN cities c ON c.id=pc.city_id
            WHERE v.id=:v AND v.is_active AND p.is_active AND c.is_active""", v=variant_id, c=city_id)
        if not v:
            return "unavailable", None
        op = await q_one(s, "SELECT id FROM orders WHERE user_id=:u AND status IN "
                            "('AWAITING_PAYMENT','PAYMENT_REVIEW','PAYMENT_REJECTED')", u=user["id"])
        if op:
            return "open_exists", op["id"]
        deadline = now_utc() + timedelta(minutes=CFG.deadline_min)
        try:
            async with s.begin_nested():
                row = await q_one(s, """INSERT INTO orders(user_id,city_id,variant_id,total_price,currency,
                    idempotency_key,payment_deadline_at) VALUES(:u,:c,:v,:pr,:cur,:k,:dl) RETURNING id""",
                                  u=user["id"], c=city_id, v=variant_id, pr=v["price"], cur=CFG.currency, k=key,
                                  dl=deadline)
        except IntegrityError:
            ex = await q_one(s, "SELECT id FROM orders WHERE idempotency_key=:k", k=key)
            if ex:
                return "dup", ex["id"]
            op = await q_one(s, "SELECT id FROM orders WHERE user_id=:u AND status IN "
                                "('AWAITING_PAYMENT','PAYMENT_REVIEW','PAYMENT_REJECTED')", u=user["id"])
            return "open_exists", op["id"] if op else None
        oid = row["id"]
        pickup = {k: v[k] for k in ("pickup_name", "pickup_address", "pickup_instructions", "map_url",
                                    "contact_info", "working_hours")}
        await q_exec(s, """INSERT INTO order_items(order_id,product_id,variant_id,product_name,attrs,image_file_id,
            city_name,pickup,unit_price,currency) VALUES(:o,:p,:v,:n,CAST(:a AS JSONB),:img,:cn,CAST(:pk AS JSONB),:pr,:cur)""",
                     o=oid, p=v["pid"], v=v["vid"], n=v["pname"], a=json.dumps(jl(v["attrs"]), ensure_ascii=False),
                     img=v["img"], cn=v["cname"], pk=json.dumps(pickup, ensure_ascii=False), pr=v["price"],
                     cur=CFG.currency)
        await q_exec(s, "INSERT INTO order_status_history(order_id,from_status,to_status,to_pay,actor) "
                        "VALUES(:o,NULL,'AWAITING_PAYMENT','AWAITING_RECEIPT',:a)", o=oid, a=user["telegram_id"])
        await audit(s, user["telegram_id"], "order_created", "order", oid, price=str(v["price"]))
        o = await load_order(s, oid)
        await notify_staff(s, "🆕 <b>Новый заказ</b>\n\n" + staff_card(o), [[("Взять заказ", f"a:claim:{oid}")]])
        return "ok", oid


async def close_open_payment(s, oid: int, status: str, reason: str | None = None) -> None:
    await q_exec(s, "UPDATE payments SET status=:st, decision_reason=COALESCE(decision_reason,:r) "
                    "WHERE order_id=:o AND status IN ('AWAITING_RECEIPT','UNDER_REVIEW')", st=status, r=reason, o=oid)


async def payment_method_available(method: str) -> bool:
    if method == "USDT_TRC20":
        return bool(await get_setting("usdt_wallet"))
    return (await get_setting("card_enabled")) == "1" and bool(await get_setting("card_instructions"))


async def choose_payment(user_id: int, oid: int, method: str) -> tuple[str, dict | None]:
    async with tx() as s:
        o = await q_one(s, "SELECT id,user_id,status,payment_deadline_at,total_price,currency FROM orders "
                           "WHERE id=:i FOR UPDATE", i=oid)
        if not o or o["user_id"] != user_id:
            return "forbidden", None
        if o["status"] not in ("AWAITING_PAYMENT", "PAYMENT_REJECTED"):
            return "state", o
        if not o["payment_deadline_at"] or o["payment_deadline_at"] <= now_utc():
            return "expired", o
        if not await payment_method_available(method):
            return "unavailable", o
        wallet = await get_setting("usdt_wallet", s) if method == "USDT_TRC20" else None
        n = await q_exec(s, "UPDATE payments SET method=:m, wallet_snapshot=:w WHERE order_id=:o "
                            "AND status='AWAITING_RECEIPT'", m=method, w=wallet, o=oid)
        if not n:
            await q_exec(s, "INSERT INTO payments(order_id,method,status,amount,currency,wallet_snapshot) "
                            "VALUES(:o,:m,'AWAITING_RECEIPT',:a,:c,:w)",
                         o=oid, m=method, a=o["total_price"], c=o["currency"], w=wallet)
        await q_exec(s, "UPDATE orders SET payment_method=:m, updated_at=now() WHERE id=:o", m=method, o=oid)
        return "ok", o


async def payment_instructions(method: str, o: dict) -> str:
    deadline = fmt_dt(o["payment_deadline_at"])
    if method == "USDT_TRC20":
        wallet = await get_setting("usdt_wallet")
        extra = await get_setting("usdt_instructions")
        t = (f"<b>Оплата USDT (сеть TRC20)</b>\n\nСумма заказа: <b>{money(o['total_price'], o['currency'])}</b>\n"
             f"Адрес кошелька:\n<code>{e(wallet)}</code>\n\n"
             "⚠️ Перед переводом внимательно проверьте <b>сеть (TRC20)</b> и <b>адрес</b>. "
             "Перевод в другую сеть или на другой адрес может привести к потере средств.\n")
    else:
        extra = await get_setting("card_instructions")
        t = f"<b>Оплата банковской картой</b>\n\nСумма заказа: <b>{money(o['total_price'], o['currency'])}</b>\n"
    if extra:
        t += f"\n{e(extra)}\n"
    help_t = await get_setting("payment_help_text")
    if help_t:
        t += f"\n<b>Помощь:</b> {e(help_t)}\n"
    t += (f"\nПосле оплаты отправьте сюда <b>чек в виде фото или PDF-файла</b> до <b>{deadline}</b>. "
          "Если чек не будет отправлен вовремя, заказ отменится автоматически и его нельзя будет вернуть.\n"
          "Загрузка чека не означает подтверждение оплаты: платёж проверяет администратор вручную.")
    return t


async def cancel_timeout(s, oid: int, notify_customer: bool) -> bool:
    o = await load_order(s, oid, lock=True)
    if not o or o["status"] not in ("AWAITING_PAYMENT", "PAYMENT_REJECTED"):
        return False
    reason = "Время на оплату истекло"
    await transition(s, oid, "CANCELLED_PAYMENT_TIMEOUT", pay="NOT_STARTED", actor=None, reason=reason)
    await close_open_payment(s, oid, "CANCELLED", "timeout")
    await audit(s, None, "order_cancelled_timeout", "order", oid)
    if notify_customer:
        await outbox_add(s, o["tg_id"], "text", dedupe=f"timeout:{oid}",
                         body=f"⏰ Время на оплату истекло. Заказ «{e(o['product_name'])}» отменён автоматически и не может "
                              "быть возобновлён.\nВы можете оформить новый заказ через «Каталог».")
    await notify_responsible(s, o, f"⏰ Заказ отменён: время оплаты истекло.\nКлиент: {user_link(o)}\n"
                                   f"Товар: {e(o['product_name'])}")
    return True


async def sweep_deadlines() -> int:
    """Cancels every unpaid order whose persistent deadline passed. Safe to run concurrently."""
    n = 0
    async with tx() as s:
        rows = await q_all(s, """SELECT id FROM orders WHERE status IN ('AWAITING_PAYMENT','PAYMENT_REJECTED')
            AND payment_deadline_at <= now() ORDER BY payment_deadline_at LIMIT 50 FOR UPDATE SKIP LOCKED""")
        for r in rows:
            if await cancel_timeout(s, r["id"], notify_customer=True):
                n += 1
    return n


async def submit_receipt(user: dict, kind: str, file_id: str, unique_id: str | None, mime: str | None,
                         size: int | None) -> tuple[str, dict | None]:
    async with tx() as s:
        o = await q_one(s, "SELECT id FROM orders WHERE user_id=:u AND status IN "
                           "('AWAITING_PAYMENT','PAYMENT_REVIEW','PAYMENT_REJECTED')", u=user["id"])
        if not o:
            return "no_order", None
        o = await load_order(s, o["id"], lock=True)
        if o["status"] == "PAYMENT_REVIEW":
            return "already", o
        if o["status"] not in ("AWAITING_PAYMENT", "PAYMENT_REJECTED"):
            return "closed", o
        if not o["payment_deadline_at"] or o["payment_deadline_at"] <= now_utc():
            await cancel_timeout(s, o["id"], notify_customer=False)
            return "expired", o
        pay = await q_one(s, "SELECT id FROM payments WHERE order_id=:o AND status='AWAITING_RECEIPT' FOR UPDATE",
                          o=o["id"])
        if not pay:
            return "no_method", o
        await q_exec(s, "INSERT INTO receipts(order_id,payment_id,kind,file_id,file_unique_id,mime_type,file_size) "
                        "VALUES(:o,:p,:k,:f,:u,:m,:s)", o=o["id"], p=pay["id"], k=kind, f=file_id, u=unique_id, m=mime,
                     s=size)
        await q_exec(s, "UPDATE payments SET status='UNDER_REVIEW' WHERE id=:p", p=pay["id"])
        await transition(s, o["id"], "PAYMENT_REVIEW", pay="UNDER_REVIEW", actor=user["telegram_id"], deadline=None)
        await audit(s, user["telegram_id"], "receipt_submitted", "order", o["id"], kind=kind)
        o = await load_order(s, o["id"])
        oid = o["id"]
        btns = [[("Открыть заказ", f"o:v:{oid}")]]
        if not o["assigned_to"]:
            btns.insert(0, [("Взять заказ", f"a:claim:{oid}")])
        await notify_responsible(s, o, "🧾 <b>Получен чек на проверку</b>\n\n" + staff_card(o), btns)
        return "ok", o


async def claim_order(oid: int, actor: int) -> tuple[str, dict | None]:
    async with tx() as s:
        r = await q_one(s, """UPDATE orders SET assigned_to=:a, assigned_at=now(), updated_at=now()
            WHERE id=:i AND assigned_to IS NULL AND status NOT IN ('DISPATCHED','REJECTED_BEFORE_PAYMENT',
            'CANCELLED_BY_CUSTOMER','CANCELLED_PAYMENT_TIMEOUT') RETURNING id""", a=actor, i=oid)
        if not r:
            cur = await q_one(s, "SELECT assigned_to, status FROM orders WHERE id=:i", i=oid)
            if not cur:
                return "missing", None
            return ("taken" if cur["assigned_to"] else "closed"), cur
        await q_exec(s, "INSERT INTO order_assignments(order_id,admin_id,assigned_by) VALUES(:o,:a,:a)", o=oid, a=actor)
        await audit(s, actor, "order_claimed", "order", oid)
        return "ok", await load_order(s, oid)


async def reassign_order(oid: int, new_admin: int, actor: int) -> str:
    async with tx() as s:
        o = await q_one(s, "SELECT status, assigned_to FROM orders WHERE id=:i FOR UPDATE", i=oid)
        if not o or o["status"] in FINAL:
            return "closed"
        await q_exec(s, "UPDATE order_assignments SET released_at=now() WHERE order_id=:o AND released_at IS NULL", o=oid)
        await q_exec(s, "INSERT INTO order_assignments(order_id,admin_id,assigned_by) VALUES(:o,:a,:b)",
                     o=oid, a=new_admin, b=actor)
        await q_exec(s, "UPDATE orders SET assigned_to=:a, assigned_at=now() WHERE id=:o", a=new_admin, o=oid)
        await audit(s, actor, "order_reassigned", "order", oid, to=new_admin, previous=o["assigned_to"])
        await outbox_add(s, new_admin, "text", body="Вам передан заказ.", buttons=[[("Открыть заказ", f"o:v:{oid}")]])
        return "ok"


async def approve_payment(oid: int, actor: int, role: str) -> str:
    async with tx() as s:
        o = await load_order(s, oid, lock=True)
        if not o:
            return "missing"
        if not authorized(o, actor, role):
            return "forbidden"
        if o["status"] != "PAYMENT_REVIEW":
            return "state"
        await transition(s, oid, "PAID", pay="CONFIRMED", actor=actor)
        await q_exec(s, "UPDATE payments SET status='CONFIRMED', decided_by=:a, decided_at=now() "
                        "WHERE order_id=:o AND status='UNDER_REVIEW'", a=actor, o=oid)
        await q_exec(s, "UPDATE receipts SET status='APPROVED' WHERE order_id=:o AND status='SUBMITTED'", o=oid)
        await audit(s, actor, "payment_approved", "order", oid, method=o["payment_method"])
        await outbox_add(s, o["tg_id"], "text", dedupe=f"paid:{oid}",
                         body=f"✅ Оплата заказа «{e(o['product_name'])}» подтверждена. "
                              "Мы готовим ваш заказ и сообщим о получении отдельным сообщением.")
        await notify_responsible(s, o, f"✅ Оплата подтверждена ({actor}).\nТовар: {e(o['product_name'])}\n"
                                       f"Клиент: {user_link(o)}", exclude=actor)
        return "ok"


async def reject_payment(oid: int, actor: int, role: str, reason: str) -> str:
    async with tx() as s:
        o = await load_order(s, oid, lock=True)
        if not o:
            return "missing"
        if not authorized(o, actor, role):
            return "forbidden"
        if o["status"] != "PAYMENT_REVIEW":
            return "state"
        dl = now_utc() + timedelta(minutes=CFG.deadline_min)
        await transition(s, oid, "PAYMENT_REJECTED", pay="REJECTED", actor=actor, reason=reason, deadline=dl)
        pay = await q_one(s, "SELECT id, method, amount, currency, wallet_snapshot FROM payments "
                             "WHERE order_id=:o AND status='UNDER_REVIEW'", o=oid)
        await q_exec(s, "UPDATE payments SET status='REJECTED', decided_by=:a, decided_at=now(), decision_reason=:r "
                        "WHERE id=:p", a=actor, r=reason, p=pay["id"])
        await q_exec(s, "INSERT INTO payments(order_id,method,status,amount,currency,wallet_snapshot) "
                        "VALUES(:o,:m,'AWAITING_RECEIPT',:a,:c,:w)", o=oid, m=pay["method"], a=pay["amount"],
                     c=pay["currency"], w=pay["wallet_snapshot"])
        await q_exec(s, "UPDATE receipts SET status='REJECTED' WHERE order_id=:o AND status='SUBMITTED'", o=oid)
        await audit(s, actor, "payment_rejected", "order", oid, reason=reason)
        await outbox_add(s, o["tg_id"], "text",
                         body=f"❌ Оплата заказа «{e(o['product_name'])}» не подтверждена.\nПричина: {e(reason)}\n\n"
                              f"Вы можете отправить новый чек (фото или PDF) в течение {CFG.deadline_min} мин. — "
                              f"до {fmt_dt(dl)}. Иначе заказ будет отменён автоматически.")
        await notify_responsible(s, o, f"❌ Оплата отклонена ({actor}): {e(reason)}\nТовар: {e(o['product_name'])}",
                                 exclude=actor)
        return "ok"


async def reject_before_payment(oid: int, actor: int, role: str, reason: str) -> str:
    async with tx() as s:
        o = await load_order(s, oid, lock=True)
        if not o:
            return "missing"
        if not authorized(o, actor, role):
            return "forbidden"
        if o["status"] not in ("AWAITING_PAYMENT", "PAYMENT_REJECTED"):
            return "state"
        await transition(s, oid, "REJECTED_BEFORE_PAYMENT", pay="NOT_STARTED", actor=actor, reason=reason)
        await close_open_payment(s, oid, "CANCELLED", "rejected before payment")
        await audit(s, actor, "order_rejected_before_payment", "order", oid, reason=reason)
        await outbox_add(s, o["tg_id"], "text",
                         body=f"К сожалению, заказ «{e(o['product_name'])}» отклонён.\nПричина: {e(reason)}")
        await notify_responsible(s, o, f"Заказ отклонён до оплаты ({actor}): {e(reason)}\n"
                                       f"Товар: {e(o['product_name'])}", exclude=actor)
        return "ok"


async def customer_cancel(oid: int, user_id: int, tg_id: int) -> str:
    async with tx() as s:
        o = await load_order(s, oid, lock=True)
        if not o or o["user_id"] != user_id:
            return "forbidden"
        if o["status"] not in ("AWAITING_PAYMENT", "PAYMENT_REJECTED"):
            return "state"
        await transition(s, oid, "CANCELLED_BY_CUSTOMER", pay="NOT_STARTED", actor=tg_id, reason="Отменён клиентом")
        await close_open_payment(s, oid, "CANCELLED", "cancelled by customer")
        await audit(s, tg_id, "order_cancelled_by_customer", "order", oid)
        await notify_responsible(s, o, f"Клиент отменил заказ.\nКлиент: {user_link(o)}\nТовар: {e(o['product_name'])}")
        return "ok"


async def start_processing(oid: int, actor: int, role: str) -> str:
    async with tx() as s:
        o = await load_order(s, oid, lock=True)
        if not o:
            return "missing"
        if not authorized(o, actor, role):
            return "forbidden"
        if o["status"] != "PAID":
            return "state"
        await transition(s, oid, "PROCESSING", actor=actor)
        await audit(s, actor, "order_processing_started", "order", oid)
        return "ok"


def dispatch_text(o: dict, ready_at: datetime, pickup: str, extra: str | None) -> str:
    t = ("✅ <b>Ваш заказ готов к получению</b>\n\n"
         f"Товар: <b>{e(o['product_name'])}</b>\nГород: {e(o['city_name'])}\nВариант: {attrs_text(o['attrs'])}\n"
         f"Дата и время: <b>{fmt_dt(ready_at)}</b>\n\n<b>Где и как забрать:</b>\n{e(pickup)}")
    if extra:
        t += f"\n\n{e(extra)}"
    return t


async def create_dispatch(oid: int, actor: int, role: str, photo: str, ready_at: datetime, pickup: str,
                          extra: str | None) -> tuple[str, int | None]:
    async with tx() as s:
        o = await load_order(s, oid, lock=True)
        if not o:
            return "missing", None
        if not authorized(o, actor, role):
            return "forbidden", None
        if o["status"] not in ("PAID", "PROCESSING"):
            return "state", None
        pend = await q_one(s, """SELECT 1 AS x FROM outbox WHERE status='PENDING' AND dedupe_key LIKE :p""",
                           p=f"dispatch:{oid}:%")
        if pend:
            return "pending", None
        if o["status"] == "PAID":
            await transition(s, oid, "PROCESSING", actor=actor)
        d = await q_one(s, """INSERT INTO order_dispatches(order_id,photo_file_id,ready_at,pickup_info,extra_message,
            sent_by) VALUES(:o,:p,:r,:pk,:x,:a) RETURNING id""", o=oid, p=photo, r=ready_at, pk=pickup, x=extra, a=actor)
        await outbox_add(s, o["tg_id"], "photo", body=dispatch_text(o, ready_at, pickup, extra), file_id=photo,
                         dedupe=f"dispatch:{oid}:{d['id']}", hook=f"dispatch:{oid}:{d['id']}")
        await audit(s, actor, "dispatch_queued", "order", oid, ready_at=ready_at.isoformat())
        return "ok", d["id"]


async def finalize_dispatch(oid: int, did: int) -> None:
    async with tx() as s:
        await q_exec(s, "UPDATE order_dispatches SET sent_at=now() WHERE id=:d", d=did)
        o = await load_order(s, oid, lock=True)
        if o and o["status"] == "PROCESSING":
            d = await q_one(s, "SELECT sent_by FROM order_dispatches WHERE id=:d", d=did)
            await transition(s, oid, "DISPATCHED", actor=d["sent_by"])
            await audit(s, d["sent_by"], "order_dispatched", "order", oid)
            await notify_responsible(s, o, f"📬 Клиент уведомлён о получении заказа «{e(o['product_name'])}».")


async def dispatch_failed(oid: int, did: int, err: str) -> None:
    async with tx() as s:
        await q_exec(s, "UPDATE order_dispatches SET failed_note=:n WHERE id=:d", n=err[:300], d=did)
        o = await load_order(s, oid)
        if o:
            await audit(s, None, "dispatch_failed", "order", oid, error=err[:200])
            await notify_responsible(
                s, o, f"⚠️ Не удалось доставить клиенту уведомление о получении заказа «{e(o['product_name'])}». "
                      "Статус не изменён. Откройте заказ и повторите отправку.", [[("Открыть заказ", f"o:v:{oid}")]])


# ------------------------------------- support ---------------------------------------


async def support_add(user: dict, body: str | None, media_type: str | None, file_id: str | None) -> tuple[int, bool, int | None]:
    """Stores a customer message. Returns (conversation_id, is_new, assigned_to)."""
    async with tx() as s:
        c = await q_one(s, "SELECT id, assigned_to FROM support_conversations WHERE user_id=:u AND status='OPEN' "
                           "FOR UPDATE", u=user["id"])
        new = False
        if not c:
            c = await q_one(s, "INSERT INTO support_conversations(user_id) VALUES(:u) RETURNING id, assigned_to",
                            u=user["id"])
            new = True
        await q_exec(s, "INSERT INTO support_messages(conversation_id,sender_role,sender_id,body,media_type,media_file_id) "
                        "VALUES(:c,'CUSTOMER',:s,:b,:m,:f)", c=c["id"], s=user["telegram_id"], b=body, m=media_type, f=file_id)
        await q_exec(s, "UPDATE support_conversations SET last_message_at=now() WHERE id=:c", c=c["id"])
        who = user_link({**user, "tg_id": user["telegram_id"]})
        snippet = e(trunc(body, 500)) if body else f"[{'фото' if media_type == 'photo' else 'файл'}]"
        if new:
            await audit(s, user["telegram_id"], "support_opened", "support", c["id"])
            await notify_staff(s, f"💬 <b>Новое обращение</b>\n{who}\n\n{snippet}",
                               [[("Взять обращение", f"s:claim:{c['id']}")], [("Открыть", f"s:v:{c['id']}")]])
        elif c["assigned_to"]:
            ids = list({c["assigned_to"], CFG.owner_id})
            for tid in ids:
                await outbox_add(s, tid, "text", body=f"💬 {who}:\n{snippet}", buttons=[[("Ответить", f"s:r:{c['id']}")]])
                if media_type and file_id:
                    await outbox_add(s, tid, media_type, body="", file_id=file_id)
        if new and media_type and file_id:
            for tid in await staff_ids(s):
                await outbox_add(s, tid, media_type, body="", file_id=file_id)
        return c["id"], new, c["assigned_to"]


async def claim_conversation(cid: int, actor: int) -> str:
    async with tx() as s:
        r = await q_one(s, "UPDATE support_conversations SET assigned_to=:a, assigned_at=now() WHERE id=:c "
                           "AND assigned_to IS NULL AND status='OPEN' RETURNING id", a=actor, c=cid)
        if not r:
            cur = await q_one(s, "SELECT assigned_to, status FROM support_conversations WHERE id=:c", c=cid)
            return "missing" if not cur else ("closed" if cur["status"] != "OPEN" else "taken")
        await audit(s, actor, "support_claimed", "support", cid)
        return "ok"


async def staff_reply(cid: int, actor: int, role: str, body: str | None, media_type: str | None,
                      file_id: str | None) -> str:
    async with tx() as s:
        c = await q_one(s, "SELECT c.id, c.status, c.assigned_to, u.telegram_id AS tg FROM support_conversations c "
                           "JOIN users u ON u.id=c.user_id WHERE c.id=:c FOR UPDATE OF c", c=cid)
        if not c:
            return "missing"
        if c["status"] != "OPEN":
            return "closed"
        if not (role == "owner" or c["assigned_to"] == actor):
            return "forbidden"
        await q_exec(s, "INSERT INTO support_messages(conversation_id,sender_role,sender_id,body,media_type,media_file_id) "
                        "VALUES(:c,'STAFF',:s,:b,:m,:f)", c=cid, s=actor, b=body, m=media_type, f=file_id)
        await q_exec(s, "UPDATE support_conversations SET last_message_at=now() WHERE id=:c", c=cid)
        if media_type and file_id:
            await outbox_add(s, c["tg"], media_type, body=f"💬 <b>Поддержка:</b>\n{e(body)}" if body else "💬 Поддержка:",
                             file_id=file_id)
        else:
            await outbox_add(s, c["tg"], "text", body=f"💬 <b>Поддержка:</b>\n{e(body or '')}")
        return "ok"


async def set_conversation_status(cid: int, actor: int, role: str, close: bool) -> str:
    async with tx() as s:
        c = await q_one(s, "SELECT c.id, c.status, c.assigned_to, c.user_id, u.telegram_id AS tg FROM "
                           "support_conversations c JOIN users u ON u.id=c.user_id WHERE c.id=:c FOR UPDATE OF c", c=cid)
        if not c:
            return "missing"
        if not (role == "owner" or c["assigned_to"] == actor):
            return "forbidden"
        if close:
            if c["status"] == "CLOSED":
                return "state"
            await q_exec(s, "UPDATE support_conversations SET status='CLOSED', closed_at=now() WHERE id=:c", c=cid)
            await outbox_add(s, c["tg"], "text", body="Обращение закрыто. Если появятся вопросы, нажмите «Поддержка».")
            await audit(s, actor, "support_closed", "support", cid)
        else:
            if c["status"] == "OPEN":
                return "state"
            try:
                async with s.begin_nested():
                    await q_exec(s, "UPDATE support_conversations SET status='OPEN', closed_at=NULL WHERE id=:c", c=cid)
            except IntegrityError:
                return "has_open"
            await outbox_add(s, c["tg"], "text", body="Ваше обращение снова открыто. Вы можете написать сообщение.")
            await audit(s, actor, "support_reopened", "support", cid)
        return "ok"


# =====================================================================================
# 5. UI HELPERS, MIDDLEWARE, OUTBOX WORKER
# =====================================================================================


def ikb(*rows) -> InlineKeyboardMarkup:
    out = []
    for row in rows:
        r = []
        for t, d in row:
            if d.startswith(("http://", "https://", "tg://")):
                r.append(InlineKeyboardButton(text=t, url=d))
            else:
                r.append(InlineKeyboardButton(text=t, callback_data=d))
        out.append(r)
    return InlineKeyboardMarkup(inline_keyboard=out)


def rkb(*rows) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in r] for r in rows], resize_keyboard=True)


MENU_CUSTOMER = rkb(["Каталог", "Мои заказы"], ["Поддержка"])
MENU_BUYER_STAFF = rkb(["Каталог", "Мои покупки"], ["Назад в панель"])
MENU_OWNER = rkb(["Товары", "Города"], ["Заказы", "Администраторы"], ["Способы оплаты", "Настройки договора"],
                 ["Поддержка", "Статистика"], ["Рассылка", "Журнал действий"], ["Статус системы", "Режим покупателя"])
MENU_ADMIN = rkb(["Новые заказы", "Мои заказы"], ["Ожидают проверки оплаты", "Заказы в обработке"],
                 ["Поддержка", "Моя статистика"], ["Режим покупателя"])


def menu_for(role: str) -> ReplyKeyboardMarkup:
    return {"owner": MENU_OWNER, "admin": MENU_ADMIN}.get(role, MENU_CUSTOMER)


def cb_parts(data: str | None, n: int) -> list[str] | None:
    """Safe callback-data parsing: returns None when the shape is wrong."""
    parts = (data or "").split(":")
    return parts if len(parts) >= n and all(len(p) < 64 for p in parts) else None


def cb_int(parts: list[str], i: int) -> int | None:
    try:
        return int(parts[i])
    except (ValueError, IndexError):
        return None


async def safe_edit(cb: CallbackQuery, body: str, markup=None) -> None:
    try:
        await cb.message.edit_text(body, reply_markup=markup)
    except TelegramBadRequest as ex:
        if "not modified" in str(ex):
            return
        await cb.bot.send_message(cb.from_user.id, body, reply_markup=markup)


async def clear_markup(cb: CallbackQuery) -> None:
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass


class Flow(StatesGroup):
    input = State()


async def start_flow(bot: Bot, chat_id: int, state: FSMContext, kind: str, prompt: str, cancel: bool = True,
                     extra_buttons=None, **data) -> None:
    await state.set_state(Flow.input)
    await state.set_data({"kind": kind, **data})
    rows = list(extra_buttons or [])
    if cancel:
        rows.append([("Отмена", "x:c")])
    await bot.send_message(chat_id, prompt, reply_markup=ikb(*rows) if rows else None)


class RoleF(BaseFilter):
    def __init__(self, *roles: str):
        self.roles = roles

    async def __call__(self, event: TelegramObject, role: str = "customer") -> bool:
        return role in self.roles


# ------------------------------------- middleware ------------------------------------


class RateLimiter:
    def __init__(self, limit: int = 12, window: float = 5.0):
        self.limit, self.window, self.hits = limit, window, defaultdict(deque)

    def hit(self, uid: int) -> bool:
        now, q = time.monotonic(), self.hits[uid]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


class Gate(BaseMiddleware):
    """Private chats only, rate limiting, user upsert, role lookup and the silent agreement gate."""

    def __init__(self) -> None:
        self.rl = RateLimiter()

    async def __call__(self, handler, event, data):
        tg_user = data.get("event_from_user")
        msg = event if isinstance(event, Message) else getattr(event, "message", None)
        if tg_user is None or tg_user.is_bot or msg is None or msg.chat.type != ChatType.PRIVATE:
            return None
        if not self.rl.hit(tg_user.id):
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None
        user = await upsert_user(tg_user)
        role = await get_role(tg_user.id)
        agreement = await current_agreement()
        accepted = role in STAFF or bool(agreement and await has_accepted(user["id"], agreement["id"]))
        data.update(db_user=user, role=role, agreement=agreement, accepted=accepted)
        if not accepted:
            is_start = isinstance(event, Message) and (event.text or "").split("@")[0].split(" ")[0] == "/start"
            is_agr = isinstance(event, CallbackQuery) and (event.data or "").startswith("agr:")
            if not (is_start or is_agr):
                if isinstance(event, CallbackQuery):
                    await event.answer()  # silent: the bot waits for acceptance
                return None
        return await handler(event, data)


# ------------------------------------- outbox worker ---------------------------------


async def _outbox_mark(oid: int, status: str, err: str | None = None, retry_in: int | None = None,
                       attempts_inc: bool = False) -> None:
    async with tx() as s:
        if status == "SENT":
            await q_exec(s, "UPDATE outbox SET status='SENT', sent_at=now(), last_error=NULL WHERE id=:i", i=oid)
        elif status == "FAILED":
            await q_exec(s, "UPDATE outbox SET status='FAILED', last_error=:e, attempts=attempts+1 WHERE id=:i",
                         i=oid, e=err)
        else:
            await q_exec(s, f"UPDATE outbox SET next_attempt_at=now() + make_interval(secs => :r), last_error=:e, "
                            f"attempts=attempts+{1 if attempts_inc else 0} WHERE id=:i", i=oid, e=err, r=retry_in)


async def _run_hook(hook: str | None, ok: bool, err: str = "") -> None:
    if not hook or not hook.startswith("dispatch:"):
        return
    _, oid, did = hook.split(":")
    if ok:
        await finalize_dispatch(int(oid), int(did))
    else:
        await dispatch_failed(int(oid), int(did), err)


async def _outbox_send(bot: Bot, r: dict) -> None:
    p = jl(r["payload"])
    markup = ikb(*p["buttons"]) if p.get("buttons") else None
    cid, body, fid = r["chat_id"], p.get("text") or "", p.get("file_id")
    try:
        if r["kind"] == "photo":
            await bot.send_photo(cid, fid, caption=body or None, reply_markup=markup)
        elif r["kind"] == "document":
            await bot.send_document(cid, fid, caption=body or None, reply_markup=markup)
        else:
            await bot.send_message(cid, body, reply_markup=markup)
    except TelegramRetryAfter as ex:
        await _outbox_mark(r["id"], "RETRY", str(ex)[:200], retry_in=int(ex.retry_after) + 1)
        return
    except TelegramForbiddenError as ex:
        await _outbox_mark(r["id"], "FAILED", f"forbidden: {ex}"[:300])
        await q_exec_simple("UPDATE users SET is_bot_blocked=true WHERE telegram_id=:t", t=cid)
        await _run_hook(r.get("hook"), False, "Клиент заблокировал бота")
        return
    except TelegramBadRequest as ex:
        await _outbox_mark(r["id"], "FAILED", f"bad request: {ex}"[:300])
        log.error("outbox %s permanent failure: %s", r["id"], ex)
        await _run_hook(r.get("hook"), False, f"Telegram отклонил сообщение: {ex}")
        return
    except Exception as ex:  # network / temporary
        attempts = r["attempts"] + 1
        if attempts >= 8:
            await _outbox_mark(r["id"], "FAILED", f"gave up: {ex}"[:300])
            log.error("outbox %s gave up: %s", r["id"], ex)
            await _run_hook(r.get("hook"), False, "Не удалось связаться с Telegram")
        else:
            await _outbox_mark(r["id"], "RETRY", str(ex)[:200], retry_in=min(5 * 2 ** attempts, 300), attempts_inc=True)
        return
    await _outbox_mark(r["id"], "SENT")
    await _run_hook(r.get("hook"), True)


async def q_exec_simple(sql: str, **p) -> int:
    async with tx() as s:
        return await q_exec(s, sql, **p)


async def outbox_tick(bot: Bot) -> int:
    async with tx() as s:
        rows = await q_all(s, """UPDATE outbox SET next_attempt_at = now() + interval '60 seconds' WHERE id IN (
            SELECT id FROM outbox WHERE status='PENDING' AND next_attempt_at <= now() ORDER BY id LIMIT 20
            FOR UPDATE SKIP LOCKED) RETURNING id, chat_id, kind, payload, attempts, hook""")
    for r in sorted(rows, key=lambda x: x["id"]):
        try:
            await _outbox_send(bot, r)
        except Exception:
            log.exception("outbox row %s processing error", r["id"])
        await asyncio.sleep(0.04)  # ~25 msg/s, below Telegram's global limit
    return len(rows)


async def outbox_loop(bot: Bot) -> None:
    while True:
        try:
            HEARTBEAT["outbox"] = time.time()
            if not await outbox_tick(bot):
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("outbox loop error")
            await asyncio.sleep(5)


async def sweeper_loop(bot: Bot) -> None:
    while True:
        try:
            HEARTBEAT["sweeper"] = time.time()
            n = await sweep_deadlines()
            if n:
                log.info("deadline sweeper cancelled %s order(s)", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("deadline sweeper error")
        await asyncio.sleep(CFG.sweep_sec)


# =====================================================================================
# 6. CUSTOMER HANDLERS
# =====================================================================================

cust = Router(name="customer")
staff_r = Router(name="staff")
owner_r = Router(name="owner")
flow_r = Router(name="flow")
FLOWS: dict = {}


def flow(kind: str, roles=("customer", "admin", "owner")):
    def deco(fn):
        FLOWS[kind] = (fn, roles)
        return fn
    return deco


def display_name(u: dict) -> str:
    return e(u.get("first_name") or "друг")


async def send_offer(bot: Bot, chat_id: int, ag: dict, name: str = "") -> None:
    cap = (f"Здравствуйте{', ' + name if name else ''}! Добро пожаловать.\n\n"
           "Перед началом работы ознакомьтесь с публичной офертой (файл выше) и подтвердите, что принимаете её условия. "
           "Пока условия не приняты, каталог и заказы недоступны.")
    await bot.send_document(chat_id, ag["file_id"], caption=cap, reply_markup=ikb(
        [("Открыть договор", "agr:open")], [("Принимаю условия", f"agr:ok:{ag['version']}")]))


@cust.message(CommandStart())
async def h_start(m: Message, state: FSMContext, role: str, db_user: dict, accepted: bool, agreement: dict | None):
    await state.clear()
    if role in STAFF:
        txt = "Панель владельца." if role == "owner" else "Панель администратора."
        if role == "owner" and not agreement:
            txt += "\n\n⚠️ Договор-оферта ещё не загружен. Откройте «Настройки договора» и отправьте PDF-файл."
        await m.answer(txt, reply_markup=menu_for(role))
        return
    if not agreement:
        await m.answer("Бот ещё настраивается. Пожалуйста, попробуйте позже.")
        return
    if accepted:
        await m.answer(f"С возвращением, {display_name(db_user)}!", reply_markup=MENU_CUSTOMER)
        await show_cities(m.bot, m.chat.id)
        return
    await send_offer(m.bot, m.chat.id, agreement, display_name(db_user))


@cust.callback_query(F.data == "agr:open")
async def cb_agr_open(cb: CallbackQuery, agreement: dict | None):
    await cb.answer()
    if agreement:
        await send_offer(cb.bot, cb.from_user.id, agreement)


@cust.callback_query(F.data.startswith("agr:ok:"))
async def cb_agr_ok(cb: CallbackQuery, db_user: dict, agreement: dict | None):
    parts = cb_parts(cb.data, 3)
    ver = cb_int(parts, 2) if parts else None
    if ver is None or not agreement:
        return await cb.answer()
    res = await accept_agreement(db_user, ver)
    if res == "outdated":
        await cb.answer("Договор был обновлён. Пожалуйста, ознакомьтесь с новой версией.", show_alert=True)
        await send_offer(cb.bot, cb.from_user.id, agreement)
        return
    await cb.answer("Условия приняты")
    await clear_markup(cb)
    await cb.bot.send_message(cb.from_user.id, "Спасибо! Условия приняты. Теперь вам доступен каталог.",
                              reply_markup=MENU_CUSTOMER if await get_role(cb.from_user.id) == "customer" else None)
    await show_cities(cb.bot, cb.from_user.id)


# ------------------------------------- catalog ---------------------------------------


async def show_cities(bot: Bot, chat_id: int) -> None:
    cities = await list_active_cities()
    if not cities:
        await bot.send_message(chat_id, "Сейчас нет доступных городов. Загляните позже.")
        return
    await bot.send_message(chat_id, "Выберите город:",
                           reply_markup=ikb(*[[(c["name"], f"cat:c:{c['id']}")] for c in cities]))


@cust.message(F.text.in_({"Каталог", "Выбрать город"}))
async def h_catalog(m: Message, state: FSMContext):
    await state.clear()
    await show_cities(m.bot, m.chat.id)


@cust.message(F.text == "Назад в панель", RoleF(*STAFF))
async def h_back_panel(m: Message, state: FSMContext, role: str):
    await state.clear()
    await m.answer("Панель управления.", reply_markup=menu_for(role))


@cust.callback_query(F.data == "cat:cities")
async def cb_cities(cb: CallbackQuery):
    await cb.answer()
    cities = await list_active_cities()
    await safe_edit(cb, "Выберите город:" if cities else "Сейчас нет доступных городов.",
                    ikb(*[[(c["name"], f"cat:c:{c['id']}")] for c in cities]) if cities else None)


@cust.callback_query(F.data.startswith("cat:c:"))
async def cb_city(cb: CallbackQuery):
    await cb.answer()
    parts = cb_parts(cb.data, 3)
    cid = cb_int(parts, 2) if parts else None
    if cid is None:
        return
    prods = await list_city_products(cid)
    city = await fetchone("SELECT name FROM cities WHERE id=:c AND is_active", c=cid)
    if not city:
        return await safe_edit(cb, "Этот город сейчас недоступен.", ikb([("← Города", "cat:cities")]))
    if not prods:
        return await safe_edit(cb, f"В городе «{e(city['name'])}» пока нет товаров.", ikb([("← Города", "cat:cities")]))
    rows = [[(trunc(f"{p['name']} — от {money(p['min_price'])}", 60), f"cat:p:{cid}:{p['id']}")] for p in prods]
    rows.append([("← Города", "cat:cities")])
    await safe_edit(cb, f"Город: <b>{e(city['name'])}</b>\nВыберите товар:", ikb(*rows))


async def send_product_page(bot: Bot, chat_id: int, p: dict, city_id: int, preview: bool = False) -> None:
    caption = f"<b>{e(p['name'])}</b>\n\n{e(p.get('description') or '')}".strip()
    lines = [f"• {attrs_text(v['attrs'])} — {money(v['price'])}" for v in p["variants"]]
    if preview:
        caption += "\n\n<b>Варианты:</b>\n" + ("\n".join(lines) or "нет активных вариантов")
        kb = None
    else:
        caption += "\n\nВыберите вариант:"
        kb = ikb(*[[(trunc(f"{re.sub('<[^>]+>', '', attrs_text(v['attrs']))} — {money(v['price'])}", 60),
                     f"cat:v:{city_id}:{v['id']}")] for v in p["variants"]], [("← Товары", f"cat:c:{city_id}")])
    imgs = p.get("images") or []
    try:
        if len(imgs) == 1:
            await bot.send_photo(chat_id, imgs[0], caption=trunc(caption, 1000), reply_markup=kb)
            return
        if len(imgs) > 1:
            await bot.send_media_group(chat_id, [InputMediaPhoto(media=f) for f in imgs[:10]])
    except TelegramAPIError as ex:
        log.warning("product media unavailable: %s", ex)
        caption = "⚠️ Изображение временно недоступно.\n\n" + caption
    await bot.send_message(chat_id, trunc(caption, 4000), reply_markup=kb)


@cust.callback_query(F.data.startswith("cat:p:"))
async def cb_product(cb: CallbackQuery):
    await cb.answer()
    parts = cb_parts(cb.data, 4)
    cid, pid = (cb_int(parts, 2), cb_int(parts, 3)) if parts else (None, None)
    if cid is None or pid is None:
        return
    p = await get_product_for_city(pid, cid)
    if not p or not p["variants"]:
        return await cb.bot.send_message(cb.from_user.id, "Этот товар сейчас недоступен в выбранном городе.")
    await send_product_page(cb.bot, cb.from_user.id, p, cid)


@cust.callback_query(F.data.startswith("cat:v:"))
async def cb_variant(cb: CallbackQuery):
    await cb.answer()
    parts = cb_parts(cb.data, 4)
    cid, vid = (cb_int(parts, 2), cb_int(parts, 3)) if parts else (None, None)
    if cid is None or vid is None:
        return
    v = await fetchone("""SELECT v.id, v.price, v.attrs, p.name AS pname, c.name AS cname, c.pickup_name, c.pickup_address,
        c.working_hours FROM product_variants v JOIN products p ON p.id=v.product_id
        JOIN product_cities pc ON pc.product_id=p.id AND pc.city_id=:c JOIN cities c ON c.id=pc.city_id
        WHERE v.id=:v AND v.is_active AND p.is_active AND c.is_active""", v=vid, c=cid)
    if not v:
        return await cb.bot.send_message(cb.from_user.id, "Этот вариант сейчас недоступен.")
    tok = secrets.token_hex(4)
    pick = "\n".join(x for x in (v["pickup_name"], v["pickup_address"], v["working_hours"]) if x)
    body = (f"<b>Ваш заказ</b>\n\nТовар: <b>{e(v['pname'])}</b>\nВариант: {attrs_text(jl(v['attrs']))}\n"
            f"Город: {e(v['cname'])}\nЦена: <b>{money(v['price'])}</b>\n"
            + (f"Получение (самовывоз):\n{e(pick)}\n" if pick else "Получение: самовывоз\n")
            + f"\nПосле подтверждения у вас будет {CFG.deadline_min} мин. на оплату и отправку чека.")
    await cb.bot.send_message(cb.from_user.id, body, reply_markup=ikb(
        [("Подтвердить заказ", f"ord:ok:{cid}:{vid}:{tok}")], [("Отменить", "ord:no")]))


@cust.callback_query(F.data == "ord:no")
async def cb_order_no(cb: CallbackQuery):
    await cb.answer("Отменено")
    await clear_markup(cb)


def pay_menu_kb(oid: int) -> InlineKeyboardMarkup:
    return ikb([("USDT (TRC20)", f"pay:usdt:{oid}")], [("Банковская карта", f"pay:card:{oid}")],
               [("Отменить заказ", f"my:cancel:{oid}")])


@cust.callback_query(F.data.startswith("ord:ok:"))
async def cb_order_ok(cb: CallbackQuery, db_user: dict):
    parts = cb_parts(cb.data, 5)
    cid, vid = (cb_int(parts, 2), cb_int(parts, 3)) if parts else (None, None)
    if cid is None or vid is None or not re.fullmatch(r"[0-9a-f]{8}", parts[4]):
        return await cb.answer()
    res, oid = await create_order(db_user, cid, vid, parts[4])
    await clear_markup(cb)
    if res == "unavailable":
        return await cb.answer("Товар больше недоступен", show_alert=True)
    if res == "open_exists":
        await cb.answer()
        return await cb.bot.send_message(cb.from_user.id, "У вас уже есть неоплаченный заказ. Завершите или отмените его "
                                         "в разделе «Мои заказы».")
    if res == "dup":
        return await cb.answer("Заказ уже оформлен")
    await cb.answer("Заказ оформлен")
    o = await fetchone("SELECT payment_deadline_at FROM orders WHERE id=:i", i=oid)
    await cb.bot.send_message(
        cb.from_user.id, f"✅ <b>Заказ оформлен.</b>\n\nНа оплату и отправку чека у вас {CFG.deadline_min} мин. — "
                         f"до <b>{fmt_dt(o['payment_deadline_at'])}</b>. Если чек не будет отправлен вовремя, заказ "
                         "отменится автоматически и его нельзя будет вернуть.\n\nВыберите способ оплаты:",
        reply_markup=pay_menu_kb(oid))


@cust.callback_query(F.data.startswith("pay:"))
async def cb_pay(cb: CallbackQuery, db_user: dict):
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None or parts[1] not in ("usdt", "card", "menu"):
        return await cb.answer()
    if parts[1] == "menu":
        await cb.answer()
        return await cb.bot.send_message(cb.from_user.id, "Выберите способ оплаты:", reply_markup=pay_menu_kb(oid))
    method = "USDT_TRC20" if parts[1] == "usdt" else "CARD"
    if method == "CARD" and (await get_setting("card_enabled")) != "1":
        return await cb.answer(CARD_OFF_TEXT, show_alert=True)
    res, o = await choose_payment(db_user["id"], oid, method)
    if res == "forbidden":
        return await cb.answer()
    if res == "unavailable":
        return await cb.answer(CARD_OFF_TEXT if method == "CARD" else "Этот способ оплаты временно недоступен.",
                               show_alert=True)
    if res == "expired":
        return await cb.answer("Время на оплату истекло. Заказ будет отменён.", show_alert=True)
    if res == "state":
        return await cb.answer("Этот заказ уже нельзя оплатить.", show_alert=True)
    await cb.answer()
    await cb.bot.send_message(cb.from_user.id, await payment_instructions(method, o))


# ------------------------------------- receipts --------------------------------------

RECEIPT_ONLY = ("Принимаются только фото или PDF-файл (чек об оплате). Видео, аудио, голосовые сообщения, стикеры, "
                "GIF и другие файлы не поддерживаются.")


@cust.message(StateFilter(None), F.animation | F.video | F.video_note | F.voice | F.audio | F.sticker)
async def h_bad_media(m: Message):
    await m.answer(RECEIPT_ONLY)


@cust.message(StateFilter(None), F.photo | F.document)
async def h_receipt(m: Message, db_user: dict):
    if m.photo:
        ph = m.photo[-1]
        kind, fid, uid, mime, size = "PHOTO", ph.file_id, ph.file_unique_id, "image/jpeg", ph.file_size
    else:
        d = m.document
        mime = (d.mime_type or "").lower()
        if mime == "application/pdf":
            kind = "PDF"
        elif mime in ("image/jpeg", "image/png", "image/webp"):
            kind = "PHOTO"
        else:
            return await m.answer(RECEIPT_ONLY)
        fid, uid, size = d.file_id, d.file_unique_id, d.file_size
    if size and size > CFG.receipt_max_bytes:
        return await m.answer(f"Файл слишком большой. Максимальный размер: {CFG.receipt_max_bytes // 1048576} МБ.")
    res, o = await submit_receipt(db_user, kind, fid, uid, mime, size)
    msgs = {
        "ok": "🧾 Чек получен и передан на проверку. Это ещё не подтверждение оплаты: администратор проверит платёж "
              "вручную и сообщит вам результат.",
        "already": "Ваш чек уже находится на проверке. Пожалуйста, дождитесь результата.",
        "expired": "⏰ Время на оплату истекло, заказ отменён и не может быть возобновлён. Вы можете оформить новый заказ "
                   "или написать в «Поддержка».",
        "closed": "По этому заказу чек больше не принимается. Если нужна помощь — «Поддержка».",
        "no_order": "У вас нет заказа, ожидающего оплаты, поэтому чек не нужен. Вопросы можно задать в «Поддержка».",
    }
    if res == "no_method":
        return await m.answer("Сначала выберите способ оплаты, затем отправьте чек.", reply_markup=pay_menu_kb(o["id"]))
    await m.answer(msgs[res])


# ------------------------------------- my orders -------------------------------------


async def send_my_orders(bot: Bot, chat_id: int, user_id: int, offset: int = 0) -> None:
    rows = await fetchall("SELECT id FROM orders WHERE user_id=:u ORDER BY created_at DESC, id DESC LIMIT 6 OFFSET :o",
                          u=user_id, o=offset)
    if not rows and offset == 0:
        return await bot.send_message(chat_id, "У вас пока нет заказов. Откройте «Каталог», чтобы выбрать товар.")
    for r in rows[:5]:
        async with SF() as s:
            o = await load_order(s, r["id"])
            d = await q_one(s, "SELECT ready_at, pickup_info, extra_message, sent_at FROM order_dispatches "
                               "WHERE order_id=:o AND sent_at IS NOT NULL ORDER BY id DESC LIMIT 1", o=r["id"])
        kb = None
        if o["status"] in ("AWAITING_PAYMENT", "PAYMENT_REJECTED"):
            kb = ikb([("Способ оплаты", f"pay:menu:{o['id']}")], [("Отменить заказ", f"my:cancel:{o['id']}")])
        body = customer_card(o, d)
        try:
            if o.get("image_file_id"):
                await bot.send_photo(chat_id, o["image_file_id"], caption=trunc(body, 1000), reply_markup=kb)
                continue
        except TelegramAPIError:
            pass
        await bot.send_message(chat_id, body, reply_markup=kb)
    if len(rows) > 5:
        await bot.send_message(chat_id, "Показаны не все заказы.", reply_markup=ikb([("Показать ещё",
                                                                                      f"my:more:{offset + 5}")]))


@cust.message(F.text.in_({"Мои заказы", "Мои покупки"}), ~RoleF("admin"))
@cust.message(F.text == "Мои покупки")
async def h_my_orders(m: Message, state: FSMContext, db_user: dict):
    await state.clear()
    await send_my_orders(m.bot, m.chat.id, db_user["id"])


@cust.callback_query(F.data.startswith("my:more:"))
async def cb_my_more(cb: CallbackQuery, db_user: dict):
    await cb.answer()
    parts = cb_parts(cb.data, 3)
    off = cb_int(parts, 2) if parts else None
    if off is None or off < 0:
        return
    await clear_markup(cb)
    await send_my_orders(cb.bot, cb.from_user.id, db_user["id"], off)


@cust.callback_query(F.data.startswith("my:cancel:"))
async def cb_my_cancel(cb: CallbackQuery):
    await cb.answer()
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None:
        return
    await cb.bot.send_message(cb.from_user.id, "Отменить заказ? Это действие нельзя отменить.",
                              reply_markup=ikb([("Да, отменить", f"my:cy:{oid}")], [("Нет", "ord:no")]))


@cust.callback_query(F.data.startswith("my:cy:"))
async def cb_my_cancel_yes(cb: CallbackQuery, db_user: dict):
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None:
        return await cb.answer()
    res = await customer_cancel(oid, db_user["id"], db_user["telegram_id"])
    await clear_markup(cb)
    await cb.answer()
    await cb.bot.send_message(cb.from_user.id, "Заказ отменён." if res == "ok" else "Этот заказ уже нельзя отменить.")


# ------------------------------------- support (customer) ----------------------------


@cust.message(F.text == "Поддержка", RoleF("customer"))
async def h_support(m: Message, state: FSMContext):
    await start_flow(m.bot, m.chat.id, state, "support",
                     "Напишите ваше сообщение (можно приложить фото или документ). Администратор ответит прямо в этом чате.",
                     extra_buttons=[[("Завершить диалог", "x:c")]], cancel=False)


@flow("support", roles=("customer",))
async def fl_support(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    body, mt, fid = (m.text or m.caption), None, None
    if m.photo:
        mt, fid = "photo", m.photo[-1].file_id
    elif m.document and not m.animation:
        mt, fid = "document", m.document.file_id
    elif not m.text:
        return await m.answer("В обращении можно отправлять текст, фото и документы.")
    if body and len(body) > 3000:
        return await m.answer("Сообщение слишком длинное. Сократите его до 3000 символов.")
    cid, new, assigned = await support_add(user, body, mt, fid)
    await m.answer("Ваше обращение принято. Мы ответим здесь, как только освободится администратор." if new
                   else "Сообщение отправлено.")


@cust.callback_query(F.data == "x:c")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Отменено")
    await clear_markup(cb)


@cust.message(Command("cancel"))
async def h_cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Действие отменено.")


# =====================================================================================
# 7. STAFF HANDLERS (owner + administrators): orders, receipts, dispatch, support
# =====================================================================================

staff_r.message.filter(RoleF(*STAFF))
staff_r.callback_query.filter(RoleF(*STAFF))
owner_r.message.filter(RoleF("owner"))
owner_r.callback_query.filter(RoleF("owner"))

FINAL_SQL = "('DISPATCHED','REJECTED_BEFORE_PAYMENT','CANCELLED_BY_CUSTOMER','CANCELLED_PAYMENT_TIMEOUT')"
PAGE = 8


@staff_r.message(F.text == "Режим покупателя")
async def h_buyer_mode(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Режим покупателя. Чтобы вернуться, нажмите «Назад в панель».", reply_markup=MENU_BUYER_STAFF)
    await show_cities(m.bot, m.chat.id)


async def render_orders(where: str, params: dict, title: str, prefix: str, pg: int):
    rows = await fetchall(
        f"""SELECT o.id, o.status, o.created_at, i.product_name FROM orders o JOIN order_items i ON i.order_id=o.id
            WHERE {where} ORDER BY o.created_at DESC, o.id DESC LIMIT {PAGE + 1} OFFSET :off""", off=pg * PAGE, **params)
    if not rows and pg == 0:
        return title + "\n\nЗаказов нет.", None
    btns = [[(trunc(f"{fmt_dt(r['created_at'])[:11]}{fmt_dt(r['created_at'])[11:]} • {r['product_name']} • "
                    f"{STATUS_RU[r['status']]}", 60), f"o:v:{r['id']}")] for r in rows[:PAGE]]
    nav = []
    if pg > 0:
        nav.append(("← Назад", f"{prefix}:{pg - 1}"))
    if len(rows) > PAGE:
        nav.append(("Далее →", f"{prefix}:{pg + 1}"))
    if nav:
        btns.append(nav)
    return title, ikb(*btns)


def admin_list_where(kind: str, me: int, role: str) -> tuple[str, dict, str] | None:
    if kind == "new":
        return f"o.assigned_to IS NULL AND o.status NOT IN {FINAL_SQL}", {}, "Новые заказы (без ответственного)"
    if kind == "my":
        return f"o.assigned_to=:me AND o.status NOT IN {FINAL_SQL}", {"me": me}, "Мои заказы"
    if kind == "rev":
        w = "o.status='PAYMENT_REVIEW'" + ("" if role == "owner" else " AND o.assigned_to=:me")
        return w, ({} if role == "owner" else {"me": me}), "Ожидают проверки оплаты"
    if kind == "proc":
        w = "o.status IN ('PAID','PROCESSING')" + ("" if role == "owner" else " AND o.assigned_to=:me")
        return w, ({} if role == "owner" else {"me": me}), "Заказы в обработке"
    return None


async def send_admin_list(bot: Bot, chat_id: int, kind: str, me: int, role: str, pg: int = 0, cb: CallbackQuery | None = None):
    spec = admin_list_where(kind, me, role)
    if not spec:
        return
    where, params, title = spec
    body, kb = await render_orders(where, params, f"<b>{title}</b>", f"l:{kind}", pg)
    if cb:
        await safe_edit(cb, body, kb)
    else:
        await bot.send_message(chat_id, body, reply_markup=kb)


@staff_r.message(F.text == "Новые заказы", RoleF("admin"))
async def h_l_new(m: Message, role: str):
    await send_admin_list(m.bot, m.chat.id, "new", m.from_user.id, role)


@staff_r.message(F.text == "Мои заказы", RoleF("admin"))
async def h_l_my(m: Message, role: str):
    await send_admin_list(m.bot, m.chat.id, "my", m.from_user.id, role)


@staff_r.message(F.text == "Ожидают проверки оплаты", RoleF("admin"))
async def h_l_rev(m: Message, role: str):
    await send_admin_list(m.bot, m.chat.id, "rev", m.from_user.id, role)


@staff_r.message(F.text == "Заказы в обработке", RoleF("admin"))
async def h_l_proc(m: Message, role: str):
    await send_admin_list(m.bot, m.chat.id, "proc", m.from_user.id, role)


@staff_r.callback_query(F.data.startswith("l:"))
async def cb_list(cb: CallbackQuery, role: str):
    await cb.answer()
    parts = cb_parts(cb.data, 3)
    pg = cb_int(parts, 2) if parts else None
    if pg is None or pg < 0:
        return
    await send_admin_list(cb.bot, cb.from_user.id, parts[1], cb.from_user.id, role, pg, cb)


def order_kb(o: dict, actor: int, role: str, has_receipt: bool) -> InlineKeyboardMarkup:
    oid, st, rows = o["id"], o["status"], []
    mine = authorized(o, actor, role)
    if not o["assigned_to"] and st not in FINAL:
        rows.append([("Взять заказ", f"a:claim:{oid}")])
    if mine:
        if st == "PAYMENT_REVIEW":
            rows.append([("Открыть чек", f"o:rc:{oid}")])
            rows.append([("Подтвердить оплату", f"o:ap:{oid}"), ("Отклонить оплату", f"o:rj:{oid}")])
        elif has_receipt:
            rows.append([("Открыть чек", f"o:rc:{oid}")])
        if st in ("AWAITING_PAYMENT", "PAYMENT_REJECTED"):
            rows.append([("Отклонить заказ", f"o:rb:{oid}")])
        if st == "PAID":
            rows.append([("Взять в обработку", f"o:pr:{oid}"), ("Отправить заказ", f"o:dp:{oid}")])
        if st == "PROCESSING":
            rows.append([("Отправить заказ", f"o:dp:{oid}")])
        if role == "owner" and st not in FINAL:
            rows.append([("Переназначить", f"o:ra:{oid}")])
    rows.append([("Обновить", f"o:v:{oid}")])
    return ikb(*rows)


async def show_order(bot: Bot, chat_id: int, oid: int, actor: int, role: str, cb: CallbackQuery | None = None) -> None:
    async with SF() as s:
        o = await load_order(s, oid)
        if not o:
            return await bot.send_message(chat_id, "Заказ не найден.")
        if role == "admin" and o["assigned_to"] not in (None, actor):
            return await bot.send_message(chat_id, NO_RIGHTS)
        hist = await q_all(s, "SELECT * FROM order_status_history WHERE order_id=:o ORDER BY id", o=oid)
        disp = await q_one(s, "SELECT ready_at, sent_at FROM order_dispatches WHERE order_id=:o ORDER BY id DESC LIMIT 1", o=oid)
        rc = await q_one(s, "SELECT 1 AS x FROM receipts WHERE order_id=:o LIMIT 1", o=oid)
    body, kb = staff_card(o, hist, disp), order_kb(o, actor, role, bool(rc))
    if cb:
        await safe_edit(cb, body, kb)
    else:
        await bot.send_message(chat_id, body, reply_markup=kb)


@staff_r.callback_query(F.data.startswith("o:v:"))
async def cb_order_view(cb: CallbackQuery, role: str):
    await cb.answer()
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is not None:
        await show_order(cb.bot, cb.from_user.id, oid, cb.from_user.id, role, cb)


@staff_r.callback_query(F.data.startswith("a:claim:"))
async def cb_claim(cb: CallbackQuery, role: str):
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None:
        return await cb.answer()
    res, _ = await claim_order(oid, cb.from_user.id)
    if res == "ok":
        await cb.answer("Заказ закреплён за вами")
        await show_order(cb.bot, cb.from_user.id, oid, cb.from_user.id, role)
    elif res == "taken":
        await cb.answer("Этот заказ уже взял другой администратор.", show_alert=True)
    else:
        await cb.answer("Этот заказ уже закрыт или недоступен.", show_alert=True)


async def _guard(cb: CallbackQuery, role: str, need: set[str] | None = None) -> tuple[int, dict] | None:
    """Parses the order id, re-checks authorization and the current state on the server."""
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None:
        await cb.answer()
        return None
    async with SF() as s:
        o = await load_order(s, oid)
    if not o:
        await cb.answer("Заказ не найден.", show_alert=True)
        return None
    if not authorized(o, cb.from_user.id, role):
        await cb.answer(NO_RIGHTS, show_alert=True)
        return None
    if need and o["status"] not in need:
        await cb.answer("Статус заказа изменился, действие недоступно.", show_alert=True)
        return None
    return oid, o


@staff_r.callback_query(F.data.startswith("o:rc:"))
async def cb_receipt(cb: CallbackQuery, role: str):
    g = await _guard(cb, role)
    if not g:
        return
    await cb.answer()
    rows = await fetchall("SELECT kind, file_id, status, submitted_at FROM receipts WHERE order_id=:o "
                          "ORDER BY id DESC LIMIT 3", o=g[0])
    if not rows:
        return await cb.bot.send_message(cb.from_user.id, "Чеков по этому заказу нет.")
    for r in rows:
        cap = f"Чек от {fmt_dt(r['submitted_at'])} — {r['status']}. Проверьте платёж независимо, скриншот не является доказательством."
        try:
            if r["kind"] == "PDF":
                await cb.bot.send_document(cb.from_user.id, r["file_id"], caption=cap)
            else:
                await cb.bot.send_photo(cb.from_user.id, r["file_id"], caption=cap)
        except TelegramAPIError as ex:
            log.warning("receipt media unavailable: %s", ex)
            await cb.bot.send_message(cb.from_user.id, "⚠️ Файл чека недоступен в Telegram.")


@staff_r.callback_query(F.data.startswith("o:ap:"))
async def cb_approve_ask(cb: CallbackQuery, role: str):
    g = await _guard(cb, role, {"PAYMENT_REVIEW"})
    if not g:
        return
    await cb.answer()
    o = g[1]
    await cb.bot.send_message(cb.from_user.id, f"Подтвердить оплату?\nТовар: {e(o['product_name'])}\nСумма: "
                              f"{money(o['total_price'], o['currency'])}\nПлатёж проверяется вручную — убедитесь, что "
                              "средства действительно поступили.", reply_markup=ikb(
        [("Да, подтвердить", f"o:apy:{g[0]}")], [("Нет", "x:c")]))


@staff_r.callback_query(F.data.startswith("o:apy:"))
async def cb_approve(cb: CallbackQuery, role: str):
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None:
        return await cb.answer()
    res = await approve_payment(oid, cb.from_user.id, role)
    await clear_markup(cb)
    await cb.answer()
    await cb.bot.send_message(cb.from_user.id, {
        "ok": "✅ Оплата подтверждена. Клиент уведомлён.", "forbidden": NO_RIGHTS,
        "state": "Решение по этому заказу уже принято или статус изменился.", "missing": "Заказ не найден."}[res])


@staff_r.callback_query(F.data.startswith(("o:rj:", "o:rb:")))
async def cb_reject_start(cb: CallbackQuery, role: str, state: FSMContext):
    mode = "pay" if cb.data.startswith("o:rj:") else "pre"
    g = await _guard(cb, role, {"PAYMENT_REVIEW"} if mode == "pay" else {"AWAITING_PAYMENT", "PAYMENT_REJECTED"})
    if not g:
        return
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "rej_reason",
                     "Введите причину " + ("отклонения оплаты" if mode == "pay" else "отклонения заказа")
                     + " (она будет показана клиенту):", oid=g[0], mode=mode)


@flow("rej_reason", roles=STAFF)
async def fl_rej_reason(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    reason = (m.text or "").strip()
    if not 3 <= len(reason) <= 500:
        return await m.answer("Причина должна содержать от 3 до 500 символов. Введите ещё раз:")
    await state.update_data(reason=reason)
    what = "отклонить оплату" if d["mode"] == "pay" else "отклонить заказ"
    await m.answer(f"Вы собираетесь <b>{what}</b>.\nПричина: {e(reason)}\n\nКлиент получит это сообщение. Подтвердить?",
                   reply_markup=ikb([("Подтвердить", f"o:rcf:{d['oid']}")], [("Отмена", "x:c")]))


@staff_r.callback_query(F.data.startswith("o:rcf:"))
async def cb_reject_confirm(cb: CallbackQuery, role: str, state: FSMContext):
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    d = await state.get_data()
    if oid is None or d.get("kind") != "rej_reason" or d.get("oid") != oid or not d.get("reason"):
        return await cb.answer("Сессия устарела. Начните заново.", show_alert=True)
    fn = reject_payment if d["mode"] == "pay" else reject_before_payment
    res = await fn(oid, cb.from_user.id, role, d["reason"])
    await state.clear()
    await clear_markup(cb)
    await cb.answer()
    await cb.bot.send_message(cb.from_user.id, {
        "ok": "Готово. Клиент уведомлён.", "forbidden": NO_RIGHTS,
        "state": "Статус заказа изменился — действие недоступно.", "missing": "Заказ не найден."}[res])


@staff_r.callback_query(F.data.startswith("o:pr:"))
async def cb_processing(cb: CallbackQuery, role: str):
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None:
        return await cb.answer()
    res = await start_processing(oid, cb.from_user.id, role)
    await cb.answer("Заказ взят в обработку" if res == "ok" else (NO_RIGHTS if res == "forbidden" else "Действие недоступно"),
                    show_alert=res != "ok")
    if res == "ok":
        await show_order(cb.bot, cb.from_user.id, oid, cb.from_user.id, role, cb)


@staff_r.callback_query(F.data.startswith("o:ra:"))
async def cb_reassign(cb: CallbackQuery, role: str):
    if role != "owner":
        return await cb.answer(NO_RIGHTS, show_alert=True)
    parts = cb_parts(cb.data, 3)
    oid = cb_int(parts, 2) if parts else None
    if oid is None:
        return await cb.answer()
    await cb.answer()
    adm = await fetchall("SELECT telegram_id FROM admins WHERE is_active ORDER BY id")
    rows = [[(f"Администратор {a['telegram_id']}", f"o:rs:{oid}:{a['telegram_id']}")] for a in adm]
    rows.append([("Себе (владельцу)", f"o:rs:{oid}:{CFG.owner_id}")])
    await cb.bot.send_message(cb.from_user.id, "Кому передать заказ?", reply_markup=ikb(*rows))


@staff_r.callback_query(F.data.startswith("o:rs:"))
async def cb_reassign_do(cb: CallbackQuery, role: str):
    if role != "owner":
        return await cb.answer(NO_RIGHTS, show_alert=True)
    parts = cb_parts(cb.data, 4)
    oid, to = (cb_int(parts, 2), cb_int(parts, 3)) if parts else (None, None)
    if oid is None or to is None:
        return await cb.answer()
    if to != CFG.owner_id and await get_role(to) != "admin":
        return await cb.answer("Получатель не является администратором.", show_alert=True)
    res = await reassign_order(oid, to, cb.from_user.id)
    await cb.answer("Заказ передан" if res == "ok" else "Заказ уже закрыт", show_alert=res != "ok")
    await clear_markup(cb)


# ------------------------------------- dispatch flow ---------------------------------


@staff_r.callback_query(F.data.startswith("o:dp:"))
async def cb_dispatch_start(cb: CallbackQuery, role: str, state: FSMContext):
    g = await _guard(cb, role, {"PAID", "PROCESSING"})
    if not g:
        return
    await cb.answer()
    extra = [[("Использовать фото из каталога", "dp:cat")]] if g[1].get("image_file_id") else None
    await start_flow(cb.bot, cb.from_user.id, state, "disp_photo",
                     "Отправьте <b>фактическое фото товара</b> (именно фото, не файл).", extra_buttons=extra, oid=g[0])


async def _disp_ask_date(bot: Bot, chat_id: int, state: FSMContext) -> None:
    await state.update_data(kind="disp_date")
    await bot.send_message(chat_id, "Введите дату готовности/отправки в формате ДД.ММ.ГГГГ, например "
                           f"{datetime.now(TZ).strftime('%d.%m.%Y')}:", reply_markup=ikb([("Отмена", "x:c")]))


@flow("disp_photo", roles=STAFF)
async def fl_disp_photo(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    if not m.photo:
        return await m.answer("Нужно отправить именно фото товара.")
    await state.update_data(photo=m.photo[-1].file_id)
    await _disp_ask_date(m.bot, m.chat.id, state)


@staff_r.callback_query(F.data == "dp:cat")
async def cb_disp_catalog_photo(cb: CallbackQuery, state: FSMContext, role: str):
    d = await state.get_data()
    if d.get("kind") != "disp_photo":
        return await cb.answer("Сессия устарела.", show_alert=True)
    async with SF() as s:
        o = await load_order(s, d["oid"])
    if not o or not o.get("image_file_id") or not authorized(o, cb.from_user.id, role):
        return await cb.answer("Фото недоступно.", show_alert=True)
    await cb.answer()
    await state.update_data(photo=o["image_file_id"])
    await _disp_ask_date(cb.bot, cb.from_user.id, state)


@flow("disp_date", roles=STAFF)
async def fl_disp_date(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    try:
        day = datetime.strptime((m.text or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        return await m.answer("Неверный формат. Введите дату как ДД.ММ.ГГГГ:")
    if day < datetime.now(TZ).date():
        return await m.answer("Дата не может быть в прошлом. Введите дату ещё раз:")
    await state.update_data(kind="disp_time", date=day.isoformat())
    await m.answer("Введите время в формате ЧЧ:ММ (например 14:30):", reply_markup=ikb([("Отмена", "x:c")]))


@flow("disp_time", roles=STAFF)
async def fl_disp_time(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    try:
        t = datetime.strptime((m.text or "").strip(), "%H:%M").time()
    except ValueError:
        return await m.answer("Неверный формат. Введите время как ЧЧ:ММ:")
    ready = datetime.combine(datetime.fromisoformat(d["date"]).date(), t, tzinfo=TZ)
    await state.update_data(kind="disp_pickup", ready=ready.isoformat())
    await m.answer("Введите место получения и инструкции (до 600 символов) или используйте данные города из заказа:",
                   reply_markup=ikb([("Данные города из заказа", "dp:pk")], [("Отмена", "x:c")]))


async def _disp_ask_extra(bot: Bot, chat_id: int, state: FSMContext, pickup: str) -> None:
    await state.update_data(kind="disp_extra", pickup=pickup)
    await bot.send_message(chat_id, "Дополнительное сообщение клиенту (до 300 символов) или пропустите:",
                           reply_markup=ikb([("Пропустить", "dp:skip")], [("Отмена", "x:c")]))


@flow("disp_pickup", roles=STAFF)
async def fl_disp_pickup(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    txt = (m.text or "").strip()
    if not 3 <= len(txt) <= 600:
        return await m.answer("Текст должен содержать от 3 до 600 символов. Введите ещё раз:")
    await _disp_ask_extra(m.bot, m.chat.id, state, txt)


@staff_r.callback_query(F.data == "dp:pk")
async def cb_disp_city_pickup(cb: CallbackQuery, state: FSMContext, role: str):
    d = await state.get_data()
    if d.get("kind") != "disp_pickup":
        return await cb.answer("Сессия устарела.", show_alert=True)
    async with SF() as s:
        o = await load_order(s, d["oid"])
    if not o or not authorized(o, cb.from_user.id, role):
        return await cb.answer(NO_RIGHTS, show_alert=True)
    pk = o["pickup"]
    txt = "\n".join(x for x in (pk.get("pickup_name"), pk.get("pickup_address"), pk.get("pickup_instructions"),
                                pk.get("working_hours"), pk.get("contact_info"), pk.get("map_url")) if x)
    if not txt:
        return await cb.answer("В данных города нет информации о получении. Введите текст вручную.", show_alert=True)
    await cb.answer()
    await _disp_ask_extra(cb.bot, cb.from_user.id, state, trunc(txt, 600))


async def _disp_preview(bot: Bot, chat_id: int, state: FSMContext, d: dict, extra: str | None) -> None:
    async with SF() as s:
        o = await load_order(s, d["oid"])
    ready = datetime.fromisoformat(d["ready"])
    body = dispatch_text(o, ready, d["pickup"], extra)
    if len(body) > 1000:
        await state.update_data(kind="disp_pickup")
        return await bot.send_message(chat_id, "Текст уведомления слишком длинный для подписи к фото. Сократите место "
                                      "получения и инструкции и введите их заново.")
    await state.update_data(kind="disp_confirm", extra=extra)
    await bot.send_message(chat_id, "Предпросмотр сообщения клиенту:")
    await bot.send_photo(chat_id, d["photo"], caption=body, reply_markup=ikb(
        [("Отправить клиенту", "dp:send")], [("Отмена", "x:c")]))


@flow("disp_extra", roles=STAFF)
async def fl_disp_extra(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    txt = (m.text or "").strip()
    if len(txt) > 300:
        return await m.answer("Не более 300 символов. Введите ещё раз:")
    await _disp_preview(m.bot, m.chat.id, state, d, txt or None)


@staff_r.callback_query(F.data == "dp:skip")
async def cb_disp_skip(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if d.get("kind") != "disp_extra":
        return await cb.answer("Сессия устарела.", show_alert=True)
    await cb.answer()
    await _disp_preview(cb.bot, cb.from_user.id, state, d, None)


@staff_r.callback_query(F.data == "dp:send")
async def cb_disp_send(cb: CallbackQuery, state: FSMContext, role: str):
    d = await state.get_data()
    if d.get("kind") != "disp_confirm":
        return await cb.answer("Сессия устарела.", show_alert=True)
    res, _ = await create_dispatch(d["oid"], cb.from_user.id, role, d["photo"], datetime.fromisoformat(d["ready"]),
                                   d["pickup"], d.get("extra"))
    await state.clear()
    await clear_markup(cb)
    await cb.answer()
    await cb.bot.send_message(cb.from_user.id, {
        "ok": "Уведомление поставлено в очередь отправки. Статус изменится на «Отправлен» после успешной доставки клиенту.",
        "forbidden": NO_RIGHTS, "state": "Статус заказа изменился — отправка недоступна.",
        "pending": "Уведомление по этому заказу уже отправляется.", "missing": "Заказ не найден."}[res])


# ------------------------------------- support (staff) -------------------------------


async def show_conversation(bot: Bot, chat_id: int, cid: int, actor: int, role: str) -> None:
    async with SF() as s:
        c = await q_one(s, """SELECT c.id, c.status, c.assigned_to, c.created_at, u.telegram_id AS tg_id, u.username,
            u.first_name, u.last_name FROM support_conversations c JOIN users u ON u.id=c.user_id WHERE c.id=:c""", c=cid)
        if not c:
            return await bot.send_message(chat_id, "Обращение не найдено.")
        if role == "admin" and c["assigned_to"] not in (None, actor):
            return await bot.send_message(chat_id, NO_RIGHTS)
        msgs = await q_all(s, "SELECT * FROM support_messages WHERE conversation_id=:c ORDER BY id DESC LIMIT 8", c=cid)
    lines = [f"💬 <b>Обращение</b> — {'открыто' if c['status'] == 'OPEN' else 'закрыто'}", f"Клиент: {user_link(c)}",
             f"Ответственный: {c['assigned_to'] or 'не назначен'}", ""]
    for mm in reversed(msgs):
        who = "Клиент" if mm["sender_role"] == "CUSTOMER" else "Поддержка"
        media = f" [{mm['media_type']}]" if mm["media_type"] else ""
        lines.append(f"<i>{fmt_dt(mm['created_at'])}</i> {who}{media}: {e(trunc(mm['body'] or '', 300))}")
    rows = []
    if c["status"] == "OPEN":
        if not c["assigned_to"]:
            rows.append([("Взять обращение", f"s:claim:{cid}")])
        if role == "owner" or c["assigned_to"] == actor:
            rows.append([("Ответить", f"s:r:{cid}"), ("Закрыть", f"s:x:{cid}")])
    elif role == "owner" or c["assigned_to"] == actor:
        rows.append([("Открыть заново", f"s:o:{cid}")])
    await bot.send_message(chat_id, "\n".join(lines), reply_markup=ikb(*rows) if rows else None)


@staff_r.message(F.text == "Поддержка")
async def h_support_staff(m: Message, role: str, state: FSMContext):
    await state.clear()
    cond = "" if role == "owner" else " AND (c.assigned_to IS NULL OR c.assigned_to=:me)"
    rows = await fetchall(f"""SELECT c.id, c.assigned_to, c.last_message_at, u.first_name FROM support_conversations c
        JOIN users u ON u.id=c.user_id WHERE c.status='OPEN'{cond} ORDER BY c.last_message_at DESC LIMIT 15""",
                          **({} if role == "owner" else {"me": m.from_user.id}))
    btns = [[(trunc(f"{r['first_name'] or 'Клиент'} • {'мой' if r['assigned_to'] == m.from_user.id else ('занят' if r['assigned_to'] else 'свободен')} • {fmt_dt(r['last_message_at'])}", 60), f"s:v:{r['id']}")] for r in rows]
    if role == "owner":
        btns.append([("Закрытые обращения", "s:cl")])
    await m.answer("<b>Обращения</b>" if rows else "Открытых обращений нет.", reply_markup=ikb(*btns) if btns else None)


@staff_r.callback_query(F.data == "s:cl")
async def cb_support_closed(cb: CallbackQuery, role: str):
    if role != "owner":
        return await cb.answer(NO_RIGHTS, show_alert=True)
    await cb.answer()
    rows = await fetchall("""SELECT c.id, c.closed_at, u.first_name FROM support_conversations c JOIN users u ON u.id=c.user_id
        WHERE c.status='CLOSED' ORDER BY c.closed_at DESC LIMIT 15""")
    btns = [[(trunc(f"{r['first_name'] or 'Клиент'} • закрыто {fmt_dt(r['closed_at'])}", 60), f"s:v:{r['id']}")] for r in rows]
    await cb.bot.send_message(cb.from_user.id, "Закрытые обращения:" if rows else "Закрытых обращений нет.",
                              reply_markup=ikb(*btns) if btns else None)


async def _cid(cb: CallbackQuery) -> int | None:
    parts = cb_parts(cb.data, 3)
    cid = cb_int(parts, 2) if parts else None
    if cid is None:
        await cb.answer()
    return cid


@staff_r.callback_query(F.data.startswith("s:v:"))
async def cb_support_view(cb: CallbackQuery, role: str):
    cid = await _cid(cb)
    if cid is not None:
        await cb.answer()
        await show_conversation(cb.bot, cb.from_user.id, cid, cb.from_user.id, role)


async def _reply_flow(cb: CallbackQuery, state: FSMContext, cid: int) -> None:
    await start_flow(cb.bot, cb.from_user.id, state, "sup_reply",
                     "Режим ответа включён: всё, что вы отправите (текст, фото, документ), уйдёт клиенту. "
                     "Нажмите «Выйти», чтобы закончить.", extra_buttons=[[("Выйти", "x:c")]], cancel=False, cid=cid)


@staff_r.callback_query(F.data.startswith("s:claim:"))
async def cb_support_claim(cb: CallbackQuery, state: FSMContext):
    cid = await _cid(cb)
    if cid is None:
        return
    res = await claim_conversation(cid, cb.from_user.id)
    if res == "ok":
        await cb.answer("Обращение закреплено за вами")
        await _reply_flow(cb, state, cid)
    else:
        await cb.answer("Это обращение уже взял другой администратор." if res == "taken" else
                        "Обращение закрыто или не найдено.", show_alert=True)


@staff_r.callback_query(F.data.startswith("s:r:"))
async def cb_support_reply(cb: CallbackQuery, state: FSMContext, role: str):
    cid = await _cid(cb)
    if cid is None:
        return
    row = await fetchone("SELECT assigned_to, status FROM support_conversations WHERE id=:c", c=cid)
    if not row or row["status"] != "OPEN" or not (role == "owner" or row["assigned_to"] == cb.from_user.id):
        return await cb.answer(NO_RIGHTS, show_alert=True)
    await cb.answer()
    await _reply_flow(cb, state, cid)


@flow("sup_reply", roles=STAFF)
async def fl_sup_reply(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    body, mt, fid = (m.text or m.caption), None, None
    if m.photo:
        mt, fid = "photo", m.photo[-1].file_id
    elif m.document and not m.animation:
        mt, fid = "document", m.document.file_id
    elif not m.text:
        return await m.answer("Можно отправлять текст, фото и документы.")
    res = await staff_reply(d["cid"], m.from_user.id, role, body, mt, fid)
    if res != "ok":
        await state.clear()
        return await m.answer({"forbidden": NO_RIGHTS, "closed": "Обращение закрыто.", "missing": "Обращение не найдено."}[res])
    await m.answer("Отправлено ✓")


@staff_r.callback_query(F.data.startswith(("s:x:", "s:o:")))
async def cb_support_status(cb: CallbackQuery, role: str, state: FSMContext):
    cid = await _cid(cb)
    if cid is None:
        return
    close = cb.data.startswith("s:x:")
    res = await set_conversation_status(cid, cb.from_user.id, role, close)
    await cb.answer()
    if res == "ok" and close:
        await state.clear()
    await cb.bot.send_message(cb.from_user.id, {
        "ok": "Обращение закрыто. Клиент уведомлён." if close else "Обращение открыто заново. Клиент уведомлён.",
        "forbidden": NO_RIGHTS, "state": "Статус обращения уже изменён.", "missing": "Обращение не найдено.",
        "has_open": "У клиента уже есть другое открытое обращение."}[res])


# ------------------------------------- admin statistics ------------------------------


@staff_r.message(F.text == "Моя статистика", RoleF("admin"))
async def h_my_stats(m: Message):
    me = m.from_user.id
    r = await fetchone("""SELECT count(*) AS total, count(*) FILTER (WHERE status='PAYMENT_REVIEW') AS review,
        count(*) FILTER (WHERE status IN ('PAID','PROCESSING')) AS inproc,
        count(*) FILTER (WHERE status='DISPATCHED') AS done FROM orders WHERE assigned_to=:m""", m=me)
    a = {x["action"]: x["n"] for x in await fetchall(
        "SELECT action, count(*) AS n FROM audit_logs WHERE actor=:m GROUP BY action", m=me)}
    await m.answer(
        "<b>Моя статистика</b>\n\n"
        f"Заказов закреплено за мной: {r['total']}\nОжидают проверки оплаты: {r['review']}\n"
        f"В обработке (оплачены): {r['inproc']}\nОтправлено клиентам: {r['done']}\n\n"
        f"Подтверждено оплат: {a.get('payment_approved', 0)}\nОтклонено оплат: {a.get('payment_rejected', 0)}\n"
        f"Отклонено заказов до оплаты: {a.get('order_rejected_before_payment', 0)}")


# =====================================================================================
# 8. OWNER HANDLERS: products, cities, admins, payments, agreement, orders, stats, ...
# =====================================================================================

TRON_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def valid_tron_address(addr: str) -> bool:
    """Base58Check validation of a TRON address (T...)."""
    if not re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", addr):
        return False
    n = 0
    for ch in addr:
        n = n * 58 + TRON_B58.index(ch)
    try:
        raw = n.to_bytes(25, "big")
    except OverflowError:
        return False
    return raw[0] == 0x41 and hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4] == raw[21:]


def parse_attrs(s: str) -> dict:
    attrs: dict = {}
    for part in re.split(r"[;\n]", s):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError("Атрибут должен быть в формате Название=Значение")
        k, v = (x.strip() for x in part.split("=", 1))
        if not k or not v or len(k) > 32 or len(v) > 64:
            raise ValueError("Название атрибута до 32 символов, значение до 64")
        attrs[k] = v
    if len(attrs) > 10:
        raise ValueError("Не более 10 атрибутов")
    return attrs


def parse_price(s: str) -> Decimal:
    try:
        d = Decimal(s.strip().replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        raise ValueError("Цена должна быть числом, например 49.90")
    if d != d.quantize(Decimal("0.01")) or d < 0 or d > Decimal("9999999999.99"):
        raise ValueError("Цена: от 0 до 9999999999.99, не более двух знаков после запятой")
    return d.quantize(Decimal("0.01"))


# ------------------------------------- products --------------------------------------


async def render_products() -> tuple[str, InlineKeyboardMarkup]:
    rows = await fetchall("SELECT id, name, is_active FROM products ORDER BY id DESC LIMIT 30")
    btns = [[(f"{'✅' if r['is_active'] else '⛔'} {trunc(r['name'], 50)}", f"p:v:{r['id']}")] for r in rows]
    btns.append([("➕ Добавить товар", "p:new")])
    return "<b>Товары</b>" + ("" if rows else "\n\nТоваров пока нет."), ikb(*btns)


@owner_r.message(F.text == "Товары")
async def h_products(m: Message, state: FSMContext):
    await state.clear()
    t, kb = await render_products()
    await m.answer(t, reply_markup=kb)


@owner_r.callback_query(F.data == "p:list")
async def cb_prod_list(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    t, kb = await render_products()
    await safe_edit(cb, t, kb)


async def product_card(pid: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with SF() as s:
        p = await q_one(s, "SELECT id, name, description, is_active FROM products WHERE id=:p", p=pid)
        if not p:
            return None
        cities = await q_all(s, "SELECT c.name FROM product_cities pc JOIN cities c ON c.id=pc.city_id "
                                "WHERE pc.product_id=:p ORDER BY c.name", p=pid)
        n_img = (await q_one(s, "SELECT count(*) AS n FROM product_images WHERE product_id=:p", p=pid))["n"]
        vs = await q_all(s, "SELECT attrs, price, is_active FROM product_variants WHERE product_id=:p ORDER BY position, id", p=pid)
    vl = "\n".join(f"{'✅' if v['is_active'] else '⛔'} {attrs_text(jl(v['attrs']))} — {money(v['price'])}" for v in vs) or "нет"
    body = (f"<b>{e(p['name'])}</b>\n{e(p['description'] or '')}\n\nСтатус: {'опубликован' if p['is_active'] else 'скрыт'}\n"
            f"Города: {e(', '.join(c['name'] for c in cities) or 'не выбраны')}\nФото: {n_img}\n\n<b>Варианты:</b>\n{vl}")
    kb = ikb([("Название", f"p:en:{pid}"), ("Описание", f"p:ed:{pid}")],
             [("Фото", f"p:ep:{pid}"), ("Города", f"p:ec:{pid}")],
             [("Варианты и цены", f"p:vs:{pid}"), ("Предпросмотр", f"p:pv:{pid}")],
             [("Скрыть товар" if p["is_active"] else "Опубликовать товар", f"p:ta:{pid}")],
             [("← К списку", "p:list")])
    return body, kb


async def show_product_card(bot: Bot, chat_id: int, pid: int, cb: CallbackQuery | None = None) -> None:
    r = await product_card(pid)
    if not r:
        return await bot.send_message(chat_id, "Товар не найден.")
    if cb:
        await safe_edit(cb, *r)
    else:
        await bot.send_message(chat_id, r[0], reply_markup=r[1])


async def _pid(cb: CallbackQuery, idx: int = 2) -> int | None:
    parts = cb_parts(cb.data, idx + 1)
    v = cb_int(parts, idx) if parts else None
    if v is None:
        await cb.answer()
    return v


@owner_r.callback_query(F.data.startswith("p:v:"))
async def cb_prod_view(cb: CallbackQuery, state: FSMContext):
    pid = await _pid(cb)
    if pid is None:
        return
    await state.clear()
    await cb.answer()
    await show_product_card(cb.bot, cb.from_user.id, pid, cb)


@owner_r.callback_query(F.data == "p:new")
async def cb_prod_new(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "prod_new_name", "Введите название товара (2–120 символов):")


@flow("prod_new_name", roles=("owner",))
async def fl_prod_new_name(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    name = (m.text or "").strip()
    if not 2 <= len(name) <= 120:
        return await m.answer("Название должно содержать от 2 до 120 символов. Введите ещё раз:")
    await state.update_data(kind="prod_new_desc", name=name)
    await m.answer("Введите описание товара (или «-», чтобы пропустить):", reply_markup=ikb([("Отмена", "x:c")]))


@flow("prod_new_desc", roles=("owner",))
async def fl_prod_new_desc(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    desc = (m.text or "").strip()
    if len(desc) > 3000:
        return await m.answer("Описание слишком длинное (до 3000 символов). Введите ещё раз:")
    async with tx() as s:
        r = await q_one(s, "INSERT INTO products(name, description) VALUES(:n,:d) RETURNING id", n=d["name"],
                        d=None if desc == "-" else desc)
        await audit(s, m.from_user.id, "product_created", "product", r["id"], name=d["name"])
    await state.clear()
    await m.answer("Товар создан (скрыт). Добавьте фото, города и варианты, затем опубликуйте его.")
    await show_product_card(m.bot, m.chat.id, r["id"])


@owner_r.callback_query(F.data.startswith(("p:en:", "p:ed:")))
async def cb_prod_edit_text(cb: CallbackQuery, state: FSMContext):
    pid = await _pid(cb)
    if pid is None:
        return
    await cb.answer()
    name = cb.data.startswith("p:en:")
    await start_flow(cb.bot, cb.from_user.id, state, "prod_name" if name else "prod_desc",
                     "Введите новое название:" if name else "Введите новое описание (или «-», чтобы очистить):", pid=pid)


@flow("prod_name", roles=("owner",))
async def fl_prod_name(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    name = (m.text or "").strip()
    if not 2 <= len(name) <= 120:
        return await m.answer("Название должно содержать от 2 до 120 символов. Введите ещё раз:")
    async with tx() as s:
        await q_exec(s, "UPDATE products SET name=:n, updated_at=now() WHERE id=:p", n=name, p=d["pid"])
        await audit(s, m.from_user.id, "product_edited", "product", d["pid"], field="name")
    await state.clear()
    await show_product_card(m.bot, m.chat.id, d["pid"])


@flow("prod_desc", roles=("owner",))
async def fl_prod_desc(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    desc = (m.text or "").strip()
    if len(desc) > 3000:
        return await m.answer("Описание слишком длинное (до 3000 символов). Введите ещё раз:")
    async with tx() as s:
        await q_exec(s, "UPDATE products SET description=:d, updated_at=now() WHERE id=:p",
                     d=None if desc == "-" else desc, p=d["pid"])
        await audit(s, m.from_user.id, "product_edited", "product", d["pid"], field="description")
    await state.clear()
    await show_product_card(m.bot, m.chat.id, d["pid"])


@owner_r.callback_query(F.data.startswith("p:ep:"))
async def cb_prod_photos(cb: CallbackQuery, state: FSMContext):
    pid = await _pid(cb)
    if pid is None:
        return
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "prod_photo",
                     "Отправляйте фото товара (по одному или несколько). Когда закончите — нажмите «Готово».",
                     extra_buttons=[[("Готово", f"p:v:{pid}")], [("Удалить все фото", f"p:cp:{pid}")]], cancel=False, pid=pid)


@flow("prod_photo", roles=("owner",))
async def fl_prod_photo(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    if not m.photo:
        return await m.answer("Нужно отправить фото (не файл, не видео).")
    async with tx() as s:
        n = (await q_one(s, "SELECT count(*) AS n FROM product_images WHERE product_id=:p", p=d["pid"]))["n"]
        if n >= 10:
            return await m.answer("Максимум 10 фото на товар.")
        await q_exec(s, "INSERT INTO product_images(product_id,file_id,position) VALUES(:p,:f,:n)", p=d["pid"],
                     f=m.photo[-1].file_id, n=n)
        await audit(s, m.from_user.id, "product_photo_added", "product", d["pid"])
    await m.answer(f"Фото добавлено (всего {n + 1}). Отправьте ещё или нажмите «Готово».")


@owner_r.callback_query(F.data.startswith("p:cp:"))
async def cb_prod_clear_photos(cb: CallbackQuery):
    pid = await _pid(cb)
    if pid is None:
        return
    async with tx() as s:
        await q_exec(s, "DELETE FROM product_images WHERE product_id=:p", p=pid)
        await audit(s, cb.from_user.id, "product_photos_cleared", "product", pid)
    await cb.answer("Фото удалены")


async def render_product_cities(pid: int) -> tuple[str, InlineKeyboardMarkup]:
    cities = await fetchall("SELECT id, name, is_active FROM cities ORDER BY name")
    sel = {r["city_id"] for r in await fetchall("SELECT city_id FROM product_cities WHERE product_id=:p", p=pid)}
    btns = [[(f"{'✅' if c['id'] in sel else '⬜'} {c['name']}{'' if c['is_active'] else ' (скрыт)'}",
              f"p:tc:{pid}:{c['id']}")] for c in cities]
    btns.append([("Готово", f"p:v:{pid}")])
    return "Города, где товар доступен:" if cities else "Сначала добавьте города.", ikb(*btns)


@owner_r.callback_query(F.data.startswith("p:ec:"))
async def cb_prod_cities(cb: CallbackQuery):
    pid = await _pid(cb)
    if pid is None:
        return
    await cb.answer()
    await safe_edit(cb, *await render_product_cities(pid))


@owner_r.callback_query(F.data.startswith("p:tc:"))
async def cb_prod_city_toggle(cb: CallbackQuery):
    parts = cb_parts(cb.data, 4)
    pid, cid = (cb_int(parts, 2), cb_int(parts, 3)) if parts else (None, None)
    if pid is None or cid is None:
        return await cb.answer()
    async with tx() as s:
        n = await q_exec(s, "DELETE FROM product_cities WHERE product_id=:p AND city_id=:c", p=pid, c=cid)
        if not n:
            await q_exec(s, "INSERT INTO product_cities(product_id, city_id) SELECT :p, id FROM cities WHERE id=:c "
                            "ON CONFLICT DO NOTHING", p=pid, c=cid)
        await audit(s, cb.from_user.id, "product_cities_changed", "product", pid, city=cid, enabled=not n)
    await cb.answer()
    await safe_edit(cb, *await render_product_cities(pid))


async def render_variants(pid: int) -> tuple[str, InlineKeyboardMarkup]:
    vs = await fetchall("SELECT id, attrs, price, is_active FROM product_variants WHERE product_id=:p ORDER BY position, id", p=pid)
    btns = [[(trunc(f"{'✅' if v['is_active'] else '⛔'} {re.sub('<[^>]+>', '', attrs_text(jl(v['attrs'])))} — {money(v['price'])}", 60),
              f"p:vv:{v['id']}")] for v in vs]
    btns.append([("➕ Добавить вариант", f"p:vn:{pid}")])
    btns.append([("← К товару", f"p:v:{pid}")])
    return "<b>Варианты</b>" + ("" if vs else "\n\nВариантов пока нет."), ikb(*btns)


@owner_r.callback_query(F.data.startswith("p:vs:"))
async def cb_variants(cb: CallbackQuery, state: FSMContext):
    pid = await _pid(cb)
    if pid is None:
        return
    await state.clear()
    await cb.answer()
    await safe_edit(cb, *await render_variants(pid))


@owner_r.callback_query(F.data.startswith("p:vn:"))
async def cb_variant_new(cb: CallbackQuery, state: FSMContext):
    pid = await _pid(cb)
    if pid is None:
        return
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "var_new",
                     "Введите вариант в формате:\n<code>Цвет=Красный; Размер=M | 49.90</code>\n"
                     "(атрибуты любые, через «;», затем «|» и цена). Для варианта без атрибутов: <code>| 49.90</code>", pid=pid)


@flow("var_new", roles=("owner",))
async def fl_var_new(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    if "|" not in (m.text or ""):
        return await m.answer("Не найден разделитель «|». Пример: <code>Цвет=Красный | 49.90</code>")
    a, p = (m.text or "").rsplit("|", 1)
    try:
        attrs, price = parse_attrs(a), parse_price(p)
    except ValueError as ex:
        return await m.answer(f"{e(str(ex))}. Попробуйте ещё раз:")
    async with tx() as s:
        r = await q_one(s, "INSERT INTO product_variants(product_id,attrs,price,position) VALUES(:p,CAST(:a AS JSONB),:pr,"
                           "(SELECT COALESCE(MAX(position),0)+1 FROM product_variants WHERE product_id=:p)) RETURNING id",
                        p=d["pid"], a=json.dumps(attrs, ensure_ascii=False), pr=price)
        await audit(s, m.from_user.id, "variant_added", "variant", r["id"], product=d["pid"], price=str(price))
    await m.answer("Вариант добавлен. Можете отправить следующий или вернуться кнопкой ниже.",
                   reply_markup=ikb([("← К вариантам", f"p:vs:{d['pid']}")]))


async def _variant(vid: int) -> dict | None:
    r = await fetchone("SELECT id, product_id, attrs, price, is_active FROM product_variants WHERE id=:v", v=vid)
    if r:
        r["attrs"] = jl(r["attrs"])
    return r


async def show_variant(bot: Bot, chat_id: int, vid: int, cb: CallbackQuery | None = None) -> None:
    v = await _variant(vid)
    if not v:
        return await bot.send_message(chat_id, "Вариант не найден.")
    body = (f"<b>Вариант</b>\nАтрибуты: {attrs_text(v['attrs'])}\nЦена: <b>{money(v['price'])}</b>\n"
            f"Статус: {'активен' if v['is_active'] else 'отключён'}")
    kb = ikb([("Цена", f"p:vp:{vid}"), ("Атрибуты", f"p:va:{vid}")],
             [("Отключить" if v["is_active"] else "Включить", f"p:vt:{vid}")], [("← К вариантам", f"p:vs:{v['product_id']}")])
    if cb:
        await safe_edit(cb, body, kb)
    else:
        await bot.send_message(chat_id, body, reply_markup=kb)


@owner_r.callback_query(F.data.startswith("p:vv:"))
async def cb_variant_view(cb: CallbackQuery, state: FSMContext):
    vid = await _pid(cb)
    if vid is None:
        return
    await state.clear()
    await cb.answer()
    await show_variant(cb.bot, cb.from_user.id, vid, cb)


@owner_r.callback_query(F.data.startswith(("p:vp:", "p:va:")))
async def cb_variant_edit(cb: CallbackQuery, state: FSMContext):
    vid = await _pid(cb)
    if vid is None:
        return
    await cb.answer()
    price = cb.data.startswith("p:vp:")
    await start_flow(cb.bot, cb.from_user.id, state, "var_price" if price else "var_attrs",
                     "Введите новую цену, например 49.90:" if price else
                     "Введите атрибуты: <code>Цвет=Красный; Размер=M</code> (или «-», чтобы убрать все):", vid=vid)


@flow("var_price", roles=("owner",))
async def fl_var_price(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    try:
        price = parse_price(m.text or "")
    except ValueError as ex:
        return await m.answer(f"{e(str(ex))}. Попробуйте ещё раз:")
    async with tx() as s:
        old = await q_one(s, "SELECT price FROM product_variants WHERE id=:v FOR UPDATE", v=d["vid"])
        await q_exec(s, "UPDATE product_variants SET price=:p WHERE id=:v", p=price, v=d["vid"])
        await audit(s, m.from_user.id, "variant_price_changed", "variant", d["vid"], old=str(old["price"]), new=str(price))
    await state.clear()
    await m.answer("Цена обновлена. Уже созданные заказы не изменились.")
    await show_variant(m.bot, m.chat.id, d["vid"])


@flow("var_attrs", roles=("owner",))
async def fl_var_attrs(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    try:
        attrs = {} if (m.text or "").strip() == "-" else parse_attrs(m.text or "")
    except ValueError as ex:
        return await m.answer(f"{e(str(ex))}. Попробуйте ещё раз:")
    async with tx() as s:
        await q_exec(s, "UPDATE product_variants SET attrs=CAST(:a AS JSONB) WHERE id=:v", a=json.dumps(attrs, ensure_ascii=False), v=d["vid"])
        await audit(s, m.from_user.id, "variant_attrs_changed", "variant", d["vid"])
    await state.clear()
    await show_variant(m.bot, m.chat.id, d["vid"])


@owner_r.callback_query(F.data.startswith("p:vt:"))
async def cb_variant_toggle(cb: CallbackQuery):
    vid = await _pid(cb)
    if vid is None:
        return
    async with tx() as s:
        await q_exec(s, "UPDATE product_variants SET is_active = NOT is_active WHERE id=:v", v=vid)
        await audit(s, cb.from_user.id, "variant_toggled", "variant", vid)
    await cb.answer()
    await show_variant(cb.bot, cb.from_user.id, vid, cb)


@owner_r.callback_query(F.data.startswith("p:ta:"))
async def cb_prod_toggle(cb: CallbackQuery):
    pid = await _pid(cb)
    if pid is None:
        return
    async with tx() as s:
        p = await q_one(s, "SELECT is_active FROM products WHERE id=:p FOR UPDATE", p=pid)
        if not p:
            return await cb.answer("Товар не найден", show_alert=True)
        if not p["is_active"]:
            nc = (await q_one(s, "SELECT count(*) AS n FROM product_cities pc JOIN cities c ON c.id=pc.city_id AND c.is_active "
                                 "WHERE pc.product_id=:p", p=pid))["n"]
            nv = (await q_one(s, "SELECT count(*) AS n FROM product_variants WHERE product_id=:p AND is_active", p=pid))["n"]
            if not nc or not nv:
                return await cb.answer("Чтобы опубликовать товар, выберите хотя бы один активный город и добавьте "
                                       "хотя бы один активный вариант.", show_alert=True)
        await q_exec(s, "UPDATE products SET is_active = NOT is_active, updated_at=now() WHERE id=:p", p=pid)
        await audit(s, cb.from_user.id, "product_deactivated" if p["is_active"] else "product_activated", "product", pid)
    await cb.answer("Готово")
    await show_product_card(cb.bot, cb.from_user.id, pid, cb)


@owner_r.callback_query(F.data.startswith("p:pv:"))
async def cb_prod_preview(cb: CallbackQuery):
    pid = await _pid(cb)
    if pid is None:
        return
    await cb.answer()
    async with SF() as s:
        p = await q_one(s, "SELECT id, name, description FROM products WHERE id=:p", p=pid)
        if not p:
            return
        p["variants"] = await q_all(s, "SELECT id, attrs, price FROM product_variants WHERE product_id=:p AND is_active "
                                       "ORDER BY position, id", p=pid)
        for v in p["variants"]:
            v["attrs"] = jl(v["attrs"])
        p["images"] = [r["file_id"] for r in await q_all(s, "SELECT file_id FROM product_images WHERE product_id=:p "
                                                            "ORDER BY position, id", p=pid)]
    await cb.bot.send_message(cb.from_user.id, "Так товар увидит клиент:")
    await send_product_page(cb.bot, cb.from_user.id, p, 0, preview=True)


# ------------------------------------- cities ----------------------------------------

CITY_FIELDS = [("name", "Название города", True), ("pickup_name", "Название пункта выдачи", False),
               ("pickup_address", "Адрес пункта выдачи", False), ("pickup_instructions", "Инструкция по получению", False),
               ("map_url", "Ссылка на карту (http/https)", False), ("contact_info", "Контакты", False),
               ("working_hours", "Часы работы", False)]


def valid_city_value(idx: int, v: str) -> str | None:
    key = CITY_FIELDS[idx][0]
    if key == "name" and not 2 <= len(v) <= 64:
        return "Название города: от 2 до 64 символов."
    if key == "map_url" and not re.match(r"https?://\S+$", v):
        return "Ссылка должна начинаться с http:// или https://"
    if len(v) > 1000:
        return "Слишком длинный текст (до 1000 символов)."
    return None


async def render_cities() -> tuple[str, InlineKeyboardMarkup]:
    rows = await fetchall("SELECT id, name, is_active FROM cities ORDER BY name")
    btns = [[(f"{'✅' if r['is_active'] else '⛔'} {r['name']}", f"ct:v:{r['id']}")] for r in rows]
    btns.append([("➕ Добавить город", "ct:new")])
    return "<b>Города</b>" + ("" if rows else "\n\nГородов пока нет."), ikb(*btns)


@owner_r.message(F.text == "Города")
async def h_cities(m: Message, state: FSMContext):
    await state.clear()
    t, kb = await render_cities()
    await m.answer(t, reply_markup=kb)


@owner_r.callback_query(F.data == "ct:list")
async def cb_city_list(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await safe_edit(cb, *await render_cities())


async def show_city(bot: Bot, chat_id: int, cid: int, cb: CallbackQuery | None = None) -> None:
    c = await fetchone("SELECT * FROM cities WHERE id=:c", c=cid)
    if not c:
        return await bot.send_message(chat_id, "Город не найден.")
    lines = [f"<b>{e(c['name'])}</b> — {'активен' if c['is_active'] else 'отключён'}"]
    for key, label, _ in CITY_FIELDS[1:]:
        lines.append(f"{label}: {e(c[key] or '—')}")
    btns = [[(label.split(" (")[0], f"ct:e:{cid}:{i}")] for i, (_, label, _) in enumerate(CITY_FIELDS)]
    btns.append([("Отключить город" if c["is_active"] else "Включить город", f"ct:t:{cid}")])
    btns.append([("← К списку", "ct:list")])
    body = "\n".join(lines)
    if cb:
        await safe_edit(cb, body, ikb(*btns))
    else:
        await bot.send_message(chat_id, body, reply_markup=ikb(*btns))


@owner_r.callback_query(F.data.startswith("ct:v:"))
async def cb_city_view(cb: CallbackQuery, state: FSMContext):
    cid = await _pid(cb)
    if cid is None:
        return
    await state.clear()
    await cb.answer()
    await show_city(cb.bot, cb.from_user.id, cid, cb)


@owner_r.callback_query(F.data.startswith("ct:t:"))
async def cb_city_toggle(cb: CallbackQuery):
    cid = await _pid(cb)
    if cid is None:
        return
    async with tx() as s:
        await q_exec(s, "UPDATE cities SET is_active = NOT is_active, updated_at=now() WHERE id=:c", c=cid)
        await audit(s, cb.from_user.id, "city_toggled", "city", cid)
    await cb.answer("Готово")
    await show_city(cb.bot, cb.from_user.id, cid, cb)


@owner_r.callback_query(F.data == "ct:new")
async def cb_city_new(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "city_new", f"Шаг 1/{len(CITY_FIELDS)}: {CITY_FIELDS[0][1]}:", idx=0, vals={})


@flow("city_new", roles=("owner",))
async def fl_city_new(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    idx, vals, v = d["idx"], dict(d["vals"]), (m.text or "").strip()
    key, label, required = CITY_FIELDS[idx]
    if v == "-" and not required:
        vals[key] = None
    else:
        err = valid_city_value(idx, v)
        if err or not v:
            return await m.answer((err or "Поле обязательно.") + " Введите ещё раз:")
        vals[key] = v
    if idx + 1 < len(CITY_FIELDS):
        await state.update_data(idx=idx + 1, vals=vals)
        return await m.answer(f"Шаг {idx + 2}/{len(CITY_FIELDS)}: {CITY_FIELDS[idx + 1][1]} (или «-», чтобы пропустить):",
                              reply_markup=ikb([("Отмена", "x:c")]))
    try:
        async with tx() as s:
            r = await q_one(s, """INSERT INTO cities(name,pickup_name,pickup_address,pickup_instructions,map_url,contact_info,
                working_hours) VALUES(:name,:pickup_name,:pickup_address,:pickup_instructions,:map_url,:contact_info,
                :working_hours) RETURNING id""", **{k: vals.get(k) for k, _, _ in CITY_FIELDS})
            await audit(s, m.from_user.id, "city_created", "city", r["id"], name=vals["name"])
    except IntegrityError:
        await state.clear()
        return await m.answer("Город с таким названием уже существует.")
    await state.clear()
    await show_city(m.bot, m.chat.id, r["id"])


@owner_r.callback_query(F.data.startswith("ct:e:"))
async def cb_city_edit(cb: CallbackQuery, state: FSMContext):
    parts = cb_parts(cb.data, 4)
    cid, idx = (cb_int(parts, 2), cb_int(parts, 3)) if parts else (None, None)
    if cid is None or idx is None or not 0 <= idx < len(CITY_FIELDS):
        return await cb.answer()
    await cb.answer()
    hint = "" if CITY_FIELDS[idx][2] else " (или «-», чтобы очистить)"
    await start_flow(cb.bot, cb.from_user.id, state, "city_edit", f"{CITY_FIELDS[idx][1]}{hint}:", cid=cid, idx=idx)


@flow("city_edit", roles=("owner",))
async def fl_city_edit(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    key, _, required = CITY_FIELDS[d["idx"]]
    v = (m.text or "").strip()
    if v == "-" and not required:
        val = None
    else:
        err = valid_city_value(d["idx"], v)
        if err or not v:
            return await m.answer((err or "Поле обязательно.") + " Введите ещё раз:")
        val = v
    try:
        async with tx() as s:
            await q_exec(s, f"UPDATE cities SET {key}=:v, updated_at=now() WHERE id=:c", v=val, c=d["cid"])
            await audit(s, m.from_user.id, "city_edited", "city", d["cid"], field=key)
    except IntegrityError:
        return await m.answer("Город с таким названием уже существует. Введите другое название:")
    await state.clear()
    await m.answer("Сохранено. Новые данные применяются сразу, без перезапуска.")
    await show_city(m.bot, m.chat.id, d["cid"])


# ------------------------------------- administrators --------------------------------


async def render_admins() -> tuple[str, InlineKeyboardMarkup]:
    rows = await fetchall("SELECT telegram_id, created_at FROM admins WHERE is_active ORDER BY id")
    act = await fetchall("""SELECT actor, count(*) FILTER (WHERE action='order_claimed') AS claimed,
        count(*) FILTER (WHERE action='payment_approved') AS approved, count(*) FILTER (WHERE action='order_dispatched') AS sent
        FROM audit_logs WHERE actor IS NOT NULL GROUP BY actor""")
    am = {a["actor"]: a for a in act}
    lines, btns = ["<b>Администраторы</b>"], []
    for r in rows:
        a = am.get(r["telegram_id"], {"claimed": 0, "approved": 0, "sent": 0})
        lines.append(f"• <code>{r['telegram_id']}</code> — назначен {fmt_dt(r['created_at'])}; взято: {a['claimed']}, "
                     f"подтверждено оплат: {a['approved']}, отправлено: {a['sent']}")
        btns.append([(f"Удалить {r['telegram_id']}", f"ad:rm:{r['telegram_id']}")])
    if not rows:
        lines.append("\nАдминистраторов нет.")
    lines.append(f"\nМаксимум: {CFG.max_admins} (кроме владельца).")
    if len(rows) < CFG.max_admins:
        btns.append([("➕ Добавить администратора", "ad:add")])
    return "\n".join(lines), ikb(*btns) if btns else None


@owner_r.message(F.text == "Администраторы")
async def h_admins(m: Message, state: FSMContext):
    await state.clear()
    t, kb = await render_admins()
    await m.answer(t, reply_markup=kb)


@owner_r.callback_query(F.data == "ad:add")
async def cb_admin_add(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "admin_add",
                     "Введите <b>числовой Telegram ID</b> нового администратора (не @username).")


@flow("admin_add", roles=("owner",))
async def fl_admin_add(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    raw = (m.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return await m.answer("ID должен быть положительным числом. Введите ещё раз:")
    tid = int(raw)
    if tid == CFG.owner_id:
        return await m.answer("Это ID владельца — он уже имеет полный доступ.")
    if await get_role(tid) == "admin":
        return await m.answer("Этот пользователь уже администратор.")
    await state.update_data(kind="admin_confirm", tid=tid)
    await m.answer(f"Назначить администратором пользователя <code>{tid}</code>?",
                   reply_markup=ikb([("Подтвердить", "ad:addy")], [("Отмена", "x:c")]))


@owner_r.callback_query(F.data == "ad:addy")
async def cb_admin_add_yes(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if d.get("kind") != "admin_confirm":
        return await cb.answer("Сессия устарела.", show_alert=True)
    tid = d["tid"]
    try:
        async with tx() as s:
            n = await q_exec(s, "UPDATE admins SET is_active=true, removed_at=NULL, added_by=:a WHERE telegram_id=:t",
                             a=cb.from_user.id, t=tid)
            if not n:
                await q_exec(s, "INSERT INTO admins(telegram_id, added_by) VALUES(:t,:a)", t=tid, a=cb.from_user.id)
            await audit(s, cb.from_user.id, "admin_added", "admin", tid)
            await outbox_add(s, tid, "text", body="Вам назначена роль администратора. Нажмите /start, чтобы открыть панель.")
    except DBAPIError as ex:
        await state.clear()
        await clear_markup(cb)
        await cb.answer()
        return await cb.bot.send_message(cb.from_user.id, "Достигнут лимит администраторов." if "max_admins" in str(ex)
                                         else ERR_TEXT)
    await state.clear()
    await clear_markup(cb)
    await cb.answer("Администратор добавлен")
    t, kb = await render_admins()
    await cb.bot.send_message(cb.from_user.id, t, reply_markup=kb)


@owner_r.callback_query(F.data.startswith("ad:rm:"))
async def cb_admin_rm(cb: CallbackQuery):
    tid = await _pid(cb)
    if tid is None:
        return
    await cb.answer()
    await cb.bot.send_message(cb.from_user.id, f"Удалить администратора <code>{tid}</code>? Его незавершённые заказы и "
                              "обращения станут свободными.", reply_markup=ikb([("Да, удалить", f"ad:rmy:{tid}")], [("Отмена", "x:c")]))


@owner_r.callback_query(F.data.startswith("ad:rmy:"))
async def cb_admin_rm_yes(cb: CallbackQuery):
    tid = await _pid(cb)
    if tid is None:
        return
    async with tx() as s:
        n = await q_exec(s, "UPDATE admins SET is_active=false, removed_at=now() WHERE telegram_id=:t AND is_active", t=tid)
        if n:
            await q_exec(s, "UPDATE order_assignments SET released_at=now() WHERE admin_id=:t AND released_at IS NULL", t=tid)
            o = await q_exec(s, f"UPDATE orders SET assigned_to=NULL WHERE assigned_to=:t AND status NOT IN {FINAL_SQL}", t=tid)
            c = await q_exec(s, "UPDATE support_conversations SET assigned_to=NULL WHERE assigned_to=:t AND status='OPEN'", t=tid)
            await audit(s, cb.from_user.id, "admin_removed", "admin", tid, released_orders=o, released_conversations=c)
    await clear_markup(cb)
    await cb.answer("Готово")
    t, kb = await render_admins()
    await cb.bot.send_message(cb.from_user.id, t, reply_markup=kb)


# ------------------------------------- payment settings ------------------------------

PAY_TEXT_KEYS = {"usdt": ("usdt_instructions", "дополнительную инструкцию для USDT"),
                 "card": ("card_instructions", "инструкцию для оплаты картой"),
                 "help": ("payment_help_text", "справочное сообщение по оплате")}


async def render_pay_settings() -> tuple[str, InlineKeyboardMarkup]:
    wallet, card = await get_setting("usdt_wallet"), await get_setting("card_enabled") == "1"
    body = ("<b>Способы оплаты</b>\n\n"
            f"1) USDT (TRC20): {'<code>' + e(wallet) + '</code>' if wallet else 'адрес не задан — способ недоступен'}\n"
            f"   Инструкция: {'задана' if await get_setting('usdt_instructions') else 'нет'}\n\n"
            f"2) Банковская карта: <b>{'включена' if card else 'выключена'}</b> (проверка оплаты — вручную)\n"
            f"   Инструкция: {'задана' if await get_setting('card_instructions') else 'нет'}\n\n"
            f"Справка по оплате: {'задана' if await get_setting('payment_help_text') else 'нет'}")
    kb = ikb([("Изменить адрес USDT", "ps:wa")], [("Инструкция USDT", "ps:ti:usdt")],
             [("Выключить карту" if card else "Включить карту", "ps:card")], [("Инструкция для карты", "ps:ti:card")],
             [("Справка по оплате", "ps:ti:help")])
    return body, kb


@owner_r.message(F.text == "Способы оплаты")
async def h_pay_settings(m: Message, state: FSMContext):
    await state.clear()
    t, kb = await render_pay_settings()
    await m.answer(t, reply_markup=kb)


@owner_r.callback_query(F.data == "ps:wa")
async def cb_wallet(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "wallet",
                     "Введите новый адрес USDT TRC20 (начинается с T, 34 символа). Никогда не отправляйте сюда seed-фразы "
                     "и приватные ключи.")


@flow("wallet", roles=("owner",))
async def fl_wallet(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    addr = (m.text or "").strip()
    if not valid_tron_address(addr):
        return await m.answer("Это не похоже на корректный адрес TRON (TRC20). Проверьте адрес и введите ещё раз:")
    old = await get_setting("usdt_wallet")
    await state.update_data(kind="wallet_confirm", new=addr)
    await m.answer(f"<b>Смена адреса USDT TRC20</b>\n\nТекущий:\n<code>{e(old) or 'не задан'}</code>\n\nНовый:\n"
                   f"<code>{e(addr)}</code>\n\nПодтвердить изменение?",
                   reply_markup=ikb([("Подтвердить", "ps:wy")], [("Отмена", "x:c")]))


@owner_r.callback_query(F.data == "ps:wy")
async def cb_wallet_yes(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if d.get("kind") != "wallet_confirm":
        return await cb.answer("Сессия устарела.", show_alert=True)
    async with tx() as s:
        old = await get_setting("usdt_wallet", s)
        await set_setting(s, "usdt_wallet", d["new"], cb.from_user.id)
        await audit(s, cb.from_user.id, "wallet_changed", "setting", "usdt_wallet", old=old, new=d["new"])
    await state.clear()
    await clear_markup(cb)
    await cb.answer("Адрес обновлён")
    t, kb = await render_pay_settings()
    await cb.bot.send_message(cb.from_user.id, "✅ Адрес обновлён.\n\n" + t, reply_markup=kb)


@owner_r.callback_query(F.data == "ps:card")
async def cb_card_ask(cb: CallbackQuery):
    await cb.answer()
    on = await get_setting("card_enabled") == "1"
    if not on and not await get_setting("card_instructions"):
        return await cb.bot.send_message(cb.from_user.id, "Сначала задайте инструкцию для оплаты картой, затем включайте способ.")
    await cb.bot.send_message(cb.from_user.id, f"{'Выключить' if on else 'Включить'} оплату банковской картой?",
                              reply_markup=ikb([("Да", f"ps:cardy:{0 if on else 1}")], [("Отмена", "x:c")]))


@owner_r.callback_query(F.data.startswith("ps:cardy:"))
async def cb_card_set(cb: CallbackQuery):
    v = await _pid(cb)
    if v not in (0, 1):
        return await cb.answer()
    if v == 1 and not await get_setting("card_instructions"):
        return await cb.answer("Сначала задайте инструкцию для карты.", show_alert=True)
    async with tx() as s:
        await set_setting(s, "card_enabled", str(v), cb.from_user.id)
        await audit(s, cb.from_user.id, "card_payments_enabled" if v else "card_payments_disabled", "setting", "card_enabled")
    await clear_markup(cb)
    await cb.answer("Готово")
    t, kb = await render_pay_settings()
    await cb.bot.send_message(cb.from_user.id, t, reply_markup=kb)


@owner_r.callback_query(F.data.startswith("ps:ti:"))
async def cb_pay_text(cb: CallbackQuery, state: FSMContext):
    parts = cb_parts(cb.data, 3)
    if not parts or parts[2] not in PAY_TEXT_KEYS:
        return await cb.answer()
    await cb.answer()
    key, label = PAY_TEXT_KEYS[parts[2]]
    await start_flow(cb.bot, cb.from_user.id, state, "pay_text", f"Введите {label} (до 1500 символов) или «-», чтобы очистить:", key=key)


@flow("pay_text", roles=("owner",))
async def fl_pay_text(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    v = (m.text or "").strip()
    if not v or len(v) > 1500:
        return await m.answer("Текст должен быть не длиннее 1500 символов. Введите ещё раз:")
    val = "" if v == "-" else v
    async with tx() as s:
        await set_setting(s, d["key"], val, m.from_user.id)
        note = ""
        if d["key"] == "card_instructions" and not val and await get_setting("card_enabled", s) == "1":
            await set_setting(s, "card_enabled", "0", m.from_user.id)
            note = "\nОплата картой автоматически выключена: нет инструкции."
        await audit(s, m.from_user.id, "payment_text_changed", "setting", d["key"], length=len(val))
    await state.clear()
    t, kb = await render_pay_settings()
    await m.answer("Сохранено." + note + "\n\n" + t, reply_markup=kb)


# ------------------------------------- agreement (PDF) -------------------------------


@owner_r.message(F.text == "Настройки договора")
async def h_agreement(m: Message, state: FSMContext):
    await state.clear()
    ag = await current_agreement()
    kb = ikb([("Загрузить новый PDF", "ag:new")])
    if not ag:
        return await m.answer("Договор-оферта ещё не загружен. Клиенты не смогут пользоваться ботом, пока вы не "
                              "опубликуете PDF.", reply_markup=kb)
    n = (await fetchone("SELECT count(*) AS n FROM agreement_acceptances WHERE agreement_version_id=:a", a=ag["id"]))["n"]
    await m.bot.send_document(m.chat.id, ag["file_id"], caption=f"Действующая версия: <b>{ag['version']}</b>\n"
                              f"Опубликована: {fmt_dt(ag['created_at'])}\nПринявших: {n}", reply_markup=kb)


@owner_r.callback_query(F.data == "ag:new")
async def cb_agr_new(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await start_flow(cb.bot, cb.from_user.id, state, "agr_file",
                     "Отправьте новый договор-оферту <b>PDF-файлом</b> (до 20 МБ). Перед публикацией вы увидите предпросмотр.")


@flow("agr_file", roles=("owner",))
async def fl_agr_file(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    doc = m.document
    if not doc or not ((doc.mime_type or "").lower() == "application/pdf" or (doc.file_name or "").lower().endswith(".pdf")):
        return await m.answer("Нужен именно PDF-файл. Отправьте документ ещё раз:")
    if (doc.file_size or 0) > 20 * 1024 * 1024:
        return await m.answer("Файл слишком большой (максимум 20 МБ).")
    last = await fetchone("SELECT COALESCE(MAX(version),0) AS v FROM agreement_versions")
    ver = last["v"] + 1
    await state.update_data(kind="agr_confirm", file_id=doc.file_id, unique=doc.file_unique_id, name=doc.file_name,
                            size=doc.file_size, ver=ver)
    await m.bot.send_document(m.chat.id, doc.file_id, caption=f"Предпросмотр. Будет опубликована версия <b>{ver}</b>.\n"
                              "После публикации все клиенты должны будут принять новые условия перед новыми заказами.",
                              reply_markup=ikb([("Опубликовать", "ag:y")], [("Отмена", "x:c")]))


@owner_r.callback_query(F.data == "ag:y")
async def cb_agr_publish(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if d.get("kind") != "agr_confirm":
        return await cb.answer("Сессия устарела.", show_alert=True)
    async with tx() as s:
        ver = (await q_one(s, "SELECT COALESCE(MAX(version),0)+1 AS v FROM agreement_versions"))["v"]
        await q_exec(s, "UPDATE agreement_versions SET is_current=false WHERE is_current")
        r = await q_one(s, "INSERT INTO agreement_versions(version,file_id,file_unique_id,file_name,file_size,is_current,"
                           "published_by) VALUES(:v,:f,:u,:n,:s,true,:a) RETURNING id", v=ver, f=d["file_id"], u=d["unique"],
                        n=d["name"], s=d["size"], a=cb.from_user.id)
        await audit(s, cb.from_user.id, "agreement_published", "agreement", r["id"], version=ver)
    await state.clear()
    await clear_markup(cb)
    await cb.answer("Опубликовано")
    await cb.bot.send_message(cb.from_user.id, f"✅ Опубликована версия {ver}.")


# ------------------------------------- owner orders ----------------------------------


def owner_filter(kind: str, val: str) -> tuple[str, dict, str] | None:
    try:
        if kind == "all":
            return "TRUE", {}, "Все заказы"
        if kind == "st" and val in STATUS_RU:
            return "o.status=:v", {"v": val}, f"Статус: {STATUS_RU[val]}"
        if kind == "pay" and val in PAY_STATUS_RU:
            return "o.payment_status=:v", {"v": val}, f"Оплата: {PAY_STATUS_RU[val]}"
        if kind == "city":
            return "o.city_id=:v", {"v": int(val)}, "Заказы по городу"
        if kind == "prod":
            return "EXISTS (SELECT 1 FROM order_items x WHERE x.order_id=o.id AND x.product_id=:v)", {"v": int(val)}, "Заказы по товару"
        if kind == "adm":
            return (("o.assigned_to IS NULL", {}, "Без ответственного") if val == "0"
                    else ("o.assigned_to=:v", {"v": int(val)}, f"Ответственный: {int(val)}"))
        if kind == "d" and int(val) in (1, 7, 30):
            return "o.created_at >= now() - make_interval(days => :v)", {"v": int(val)}, f"За {val} дн."
    except ValueError:
        return None
    return None


@owner_r.message(F.text == "Заказы")
async def h_owner_orders(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("<b>Заказы</b>\nВыберите фильтр:", reply_markup=ikb(
        [("Все", "ow:l:all:-:0"), ("Ожидают оплаты", "ow:l:st:AWAITING_PAYMENT:0")],
        [("На проверке", "ow:l:st:PAYMENT_REVIEW:0"), ("Оплачены", "ow:l:st:PAID:0")],
        [("В обработке", "ow:l:st:PROCESSING:0"), ("Отправлены", "ow:l:st:DISPATCHED:0")],
        [("По статусу", "ow:m:st"), ("По оплате", "ow:m:pay")], [("По городу", "ow:m:city"), ("По товару", "ow:m:prod")],
        [("По администратору", "ow:m:adm"), ("По дате", "ow:m:d")]))


@owner_r.callback_query(F.data.startswith("ow:m:"))
async def cb_owner_filter_menu(cb: CallbackQuery):
    parts = cb_parts(cb.data, 3)
    if not parts:
        return await cb.answer()
    await cb.answer()
    kind, rows = parts[2], []
    if kind == "st":
        rows = [[(v, f"ow:l:st:{k}:0")] for k, v in STATUS_RU.items()]
    elif kind == "pay":
        rows = [[(v, f"ow:l:pay:{k}:0")] for k, v in PAY_STATUS_RU.items()]
    elif kind == "city":
        rows = [[(r["name"], f"ow:l:city:{r['id']}:0")] for r in await fetchall("SELECT id, name FROM cities ORDER BY name")]
    elif kind == "prod":
        rows = [[(trunc(r["name"], 50), f"ow:l:prod:{r['id']}:0")] for r in await fetchall("SELECT id, name FROM products ORDER BY name LIMIT 30")]
    elif kind == "adm":
        rows = [[("Без ответственного", "ow:l:adm:0:0")], [("Владелец", f"ow:l:adm:{CFG.owner_id}:0")]] + \
               [[(str(r["telegram_id"]), f"ow:l:adm:{r['telegram_id']}:0")] for r in await fetchall("SELECT telegram_id FROM admins WHERE is_active")]
    elif kind == "d":
        rows = [[("Сегодня (24 ч)", "ow:l:d:1:0")], [("7 дней", "ow:l:d:7:0")], [("30 дней", "ow:l:d:30:0")]]
    await cb.bot.send_message(cb.from_user.id, "Выберите значение:" if rows else "Нет данных для фильтра.",
                              reply_markup=ikb(*rows) if rows else None)


@owner_r.callback_query(F.data.startswith("ow:l:"))
async def cb_owner_list(cb: CallbackQuery):
    await cb.answer()
    parts = cb_parts(cb.data, 5)
    pg = cb_int(parts, 4) if parts else None
    spec = owner_filter(parts[2], parts[3]) if parts else None
    if pg is None or pg < 0 or not spec:
        return
    where, params, title = spec
    body, kb = await render_orders(where, params, f"<b>{e(title)}</b>", f"ow:l:{parts[2]}:{parts[3]}", pg)
    await safe_edit(cb, body, kb)


# ------------------------------------- statistics ------------------------------------


async def compute_stats(days: int | None) -> str:
    since = now_utc() - timedelta(days=days) if days else None
    rng = "(CAST(:s AS timestamptz) IS NULL OR {c} >= CAST(:s AS timestamptz))"
    o = await fetchone(f"""SELECT count(*) AS total, count(*) FILTER (WHERE status='AWAITING_PAYMENT') AS awaiting,
        count(*) FILTER (WHERE status='PAYMENT_REVIEW') AS review, count(*) FILTER (WHERE status='CANCELLED_PAYMENT_TIMEOUT') AS timeout,
        count(*) FILTER (WHERE status='DISPATCHED') AS dispatched FROM orders o WHERE {rng.format(c='o.created_at')}""", s=since)
    p = await fetchone(f"""SELECT count(*) FILTER (WHERE status='CONFIRMED') AS approved,
        count(*) FILTER (WHERE status='REJECTED' AND decided_by IS NOT NULL) AS rejected FROM payments p
        WHERE {rng.format(c='p.created_at')}""", s=since)
    bym = await fetchall(f"""SELECT method, count(*) AS n FROM payments p WHERE status='CONFIRMED' AND {rng.format(c='p.created_at')}
        GROUP BY method""", s=since)
    byc = await fetchall(f"""SELECT i.city_name AS k, count(*) AS n FROM orders o JOIN order_items i ON i.order_id=o.id
        WHERE {rng.format(c='o.created_at')} GROUP BY i.city_name ORDER BY n DESC LIMIT 10""", s=since)
    byp = await fetchall(f"""SELECT i.product_name AS k, count(*) AS n FROM orders o JOIN order_items i ON i.order_id=o.id
        WHERE {rng.format(c='o.created_at')} GROUP BY i.product_name ORDER BY n DESC LIMIT 10""", s=since)
    act = await fetchall(f"""SELECT actor, action, count(*) AS n FROM audit_logs a WHERE actor IS NOT NULL AND action IN
        ('order_claimed','payment_approved','payment_rejected','order_dispatched','order_rejected_before_payment')
        AND {rng.format(c='a.created_at')} GROUP BY actor, action ORDER BY actor""", s=since)
    lines = [f"<b>Статистика</b> ({'за ' + str(days) + ' дн.' if days else 'за всё время'})", "",
             f"Всего заказов создано: {o['total']}", f"Ожидают оплаты сейчас: {o['awaiting']}",
             f"Чеков ожидают проверки сейчас: {o['review']}", f"Подтверждённых оплат: {p['approved']}",
             f"Отклонённых оплат: {p['rejected']}", f"Отменено по таймауту: {o['timeout']}",
             f"Отправлено клиентам (выдано): {o['dispatched']}", "", "<b>Подтверждённые оплаты по способам:</b>"]
    lines += [f"• {METHOD_RU[r['method']]}: {r['n']}" for r in bym] or ["• нет"]
    lines += ["", "<b>Заказы по городам (все созданные):</b>"] + [f"• {e(r['k'])}: {r['n']}" for r in byc] or ["• нет"]
    lines += ["", "<b>Заказы по товарам (все созданные):</b>"] + [f"• {e(r['k'])}: {r['n']}" for r in byp] or ["• нет"]
    names = {"order_claimed": "взято", "payment_approved": "подтв. оплат", "payment_rejected": "откл. оплат",
             "order_dispatched": "отправлено", "order_rejected_before_payment": "откл. заказов"}
    lines += ["", "<b>Активность администраторов:</b>"]
    per: dict[int, list[str]] = defaultdict(list)
    for r in act:
        per[r["actor"]].append(f"{names[r['action']]}: {r['n']}")
    lines += [f"• <code>{k}</code> — {', '.join(v)}" for k, v in per.items()] or ["• нет"]
    lines += ["", "<i>Отменённые и отклонённые заказы не считаются оплаченными или отправленными. «Сейчас» — текущие "
              "состояния, остальное — по дате создания в выбранном периоде.</i>"]
    return "\n".join(lines)


@owner_r.message(F.text == "Статистика")
async def h_stats(m: Message):
    await m.answer(await compute_stats(None), reply_markup=ikb([("Сегодня", "st:1"), ("7 дней", "st:7"), ("30 дней", "st:30")],
                                                                [("Всё время", "st:0")]))


@owner_r.callback_query(F.data.startswith("st:"))
async def cb_stats(cb: CallbackQuery):
    v = await _pid(cb, 1)
    if v is None or v not in (0, 1, 7, 30):
        return
    await cb.answer()
    await safe_edit(cb, await compute_stats(v or None), ikb([("Сегодня", "st:1"), ("7 дней", "st:7"), ("30 дней", "st:30")],
                                                             [("Всё время", "st:0")]))


# ------------------------------------- broadcast -------------------------------------

BG_TASKS: set = set()
ELIGIBLE_SQL = """FROM users u JOIN agreement_acceptances a ON a.user_id=u.id
    JOIN agreement_versions v ON v.id=a.agreement_version_id AND v.is_current WHERE NOT u.is_bot_blocked"""


@owner_r.message(F.text == "Рассылка")
async def h_broadcast(m: Message, state: FSMContext):
    await start_flow(m.bot, m.chat.id, state, "bc_content",
                     "Отправьте текст рассылки или фото с подписью (на русском языке). Перед отправкой будет предпросмотр.")


@flow("bc_content", roles=("owner",))
async def fl_bc_content(m: Message, state: FSMContext, d: dict, role: str, user: dict):
    body, photo = (m.text or m.caption or "").strip(), (m.photo[-1].file_id if m.photo else None)
    if not body or len(body) > (1000 if photo else 4000):
        return await m.answer("Нужен текст (до 4000 символов, до 1000 для подписи к фото). Отправьте ещё раз:")
    n = (await fetchone(f"SELECT count(*) AS n {ELIGIBLE_SQL}"))["n"]
    await state.update_data(kind="bc_confirm", body=body, photo=photo)
    await m.answer("Предпросмотр:")
    if photo:
        await m.bot.send_photo(m.chat.id, photo, caption=e(body))
    else:
        await m.answer(e(body))
    await m.answer(f"Получатели: <b>{n}</b> (пользователи, принявшие действующий договор и не заблокировавшие бота). "
                   "Отправить рассылку?", reply_markup=ikb([("Отправить", "bc:y")], [("Отмена", "x:c")]))


async def run_broadcast(bot: Bot, bid: int) -> None:
    b = await fetchone("SELECT body, photo_file_id, created_by FROM broadcasts WHERE id=:b", b=bid)
    if not b:
        return
    while True:
        rows = await fetchall("SELECT d.id, u.telegram_id FROM broadcast_deliveries d JOIN users u ON u.id=d.user_id "
                              "WHERE d.broadcast_id=:b AND d.status='PENDING' ORDER BY d.id LIMIT 25", b=bid)
        if not rows:
            break
        for r in rows:
            status, err = "SENT", None
            for _ in range(3):
                try:
                    if b["photo_file_id"]:
                        await bot.send_photo(r["telegram_id"], b["photo_file_id"], caption=e(b["body"]))
                    else:
                        await bot.send_message(r["telegram_id"], e(b["body"]))
                    break
                except TelegramRetryAfter as ex:
                    await asyncio.sleep(ex.retry_after + 1)
                    status, err = "FAILED", "flood limit"
                except TelegramForbiddenError:
                    status, err = "BLOCKED", "bot blocked / account deactivated"
                    await q_exec_simple("UPDATE users SET is_bot_blocked=true WHERE telegram_id=:t", t=r["telegram_id"])
                    break
                except Exception as ex:
                    status, err = "FAILED", str(ex)[:200]
                    break
            await q_exec_simple("UPDATE broadcast_deliveries SET status=:s, error=:e, sent_at=now() WHERE id=:i",
                                s=status, e=err, i=r["id"])
            await asyncio.sleep(0.05)  # ~20 msg/s, under Telegram flood limits
    async with tx() as s:
        st = await q_one(s, "SELECT count(*) FILTER (WHERE status='SENT') AS ok, count(*) FILTER (WHERE status IN "
                            "('FAILED','BLOCKED')) AS bad FROM broadcast_deliveries WHERE broadcast_id=:b", b=bid)
        await q_exec(s, "UPDATE broadcasts SET status='FINISHED', sent=:o, failed=:f, finished_at=now() WHERE id=:b",
                     o=st["ok"], f=st["bad"], b=bid)
        await audit(s, b["created_by"], "broadcast_finished", "broadcast", bid, sent=st["ok"], failed=st["bad"])
        await outbox_add(s, b["created_by"], "text", body=f"📣 Рассылка завершена.\nДоставлено: {st['ok']}\nНе доставлено: {st['bad']}")


def spawn_broadcast(bot: Bot, bid: int) -> None:
    t = asyncio.create_task(run_broadcast(bot, bid))
    BG_TASKS.add(t)
    t.add_done_callback(BG_TASKS.discard)


@owner_r.callback_query(F.data == "bc:y")
async def cb_bc_send(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if d.get("kind") != "bc_confirm":
        return await cb.answer("Сессия устарела.", show_alert=True)
    async with tx() as s:
        b = await q_one(s, "INSERT INTO broadcasts(created_by, body, photo_file_id) VALUES(:a,:b,:p) RETURNING id",
                        a=cb.from_user.id, b=d["body"], p=d["photo"])
        n = await q_exec(s, f"INSERT INTO broadcast_deliveries(broadcast_id, user_id) SELECT :b, u.id {ELIGIBLE_SQL}", b=b["id"])
        await q_exec(s, "UPDATE broadcasts SET total=:n WHERE id=:b", n=n, b=b["id"])
        await audit(s, cb.from_user.id, "broadcast_started", "broadcast", b["id"], recipients=n)
    await state.clear()
    await clear_markup(cb)
    await cb.answer("Рассылка запущена")
    await cb.bot.send_message(cb.from_user.id, f"Рассылка запущена. Получателей: {n}. Итог придёт отдельным сообщением.")
    spawn_broadcast(cb.bot, b["id"])


# ------------------------------------- audit + status --------------------------------


async def render_audit(pg: int) -> tuple[str, InlineKeyboardMarkup | None]:
    rows = await fetchall("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 11 OFFSET :o", o=pg * 10)
    lines = ["<b>Журнал действий</b>"]
    for r in rows[:10]:
        det = jl(r["details"])
        det_s = ", ".join(f"{k}={v}" for k, v in det.items() if k not in ("old", "new")) if det else ""
        lines.append(f"{fmt_dt(r['created_at'])} • {r['actor'] or 'система'} • <code>{e(r['action'])}</code>"
                     + (f" • {e(r['entity_type'])}" if r["entity_type"] else "") + (f" • {e(trunc(det_s, 80))}" if det_s else ""))
    if not rows:
        lines.append("\nЗаписей нет.")
    nav = []
    if pg > 0:
        nav.append(("← Новее", f"au:{pg - 1}"))
    if len(rows) > 10:
        nav.append(("Старее →", f"au:{pg + 1}"))
    return "\n".join(lines), ikb(nav) if nav else None


@owner_r.message(F.text == "Журнал действий")
async def h_audit(m: Message):
    t, kb = await render_audit(0)
    await m.answer(t, reply_markup=kb)


@owner_r.callback_query(F.data.startswith("au:"))
async def cb_audit(cb: CallbackQuery):
    pg = await _pid(cb, 1)
    if pg is None or pg < 0:
        return
    await cb.answer()
    await safe_edit(cb, *await render_audit(pg))


def last_backup_info() -> str:
    try:
        files = [p for p in Path(CFG.backup_dir).glob("*") if p.is_file() and p.suffix in (".gz", ".dump", ".sql")]
        if not files:
            return "бэкапов не найдено"
        p = max(files, key=lambda x: x.stat().st_mtime)
        return f"{datetime.fromtimestamp(p.stat().st_mtime, TZ).strftime('%d.%m.%Y %H:%M')} ({p.name})"
    except OSError:
        return "каталог бэкапов недоступен"


@owner_r.message(F.text == "Статус системы")
async def h_status(m: Message):
    try:
        async with ENGINE.connect() as c:
            await c.execute(text("SELECT 1"))
        db = "доступна"
    except Exception:
        db = "НЕДОСТУПНА"
    box = await fetchone("SELECT count(*) FILTER (WHERE status='PENDING') AS pending, count(*) FILTER (WHERE status='FAILED') AS failed FROM outbox")
    due = await fetchone("SELECT count(*) AS n FROM orders WHERE status IN ('AWAITING_PAYMENT','PAYMENT_REJECTED') AND payment_deadline_at <= now() - interval '60 seconds'")
    act = await fetchone("SELECT count(*) AS n FROM orders WHERE status IN ('AWAITING_PAYMENT','PAYMENT_REJECTED')")
    def hb(k: str) -> str:
        t = HEARTBEAT.get(k)
        return f"{int(time.time() - t)} с назад" if t else "нет данных"
    up = int(time.time() - START_TS)
    errs = "\n".join(f"• {fmt_dt(t)} {e(trunc(msg, 120))}" for t, _, msg in list(ERRORS)[-5:]) or "нет"
    me = await m.bot.get_me()
    await m.answer(
        f"<b>Статус системы</b>\n\nБот: @{e(me.username or '')} — работает {up // 3600} ч {up % 3600 // 60} мин\n"
        f"База данных: {db}\nПланировщик дедлайнов: {hb('sweeper')}\nОчередь уведомлений: {hb('outbox')}\n"
        f"Уведомлений в очереди: {box['pending']}, неудачных: {box['failed']}\n"
        f"Заказов ждут оплаты: {act['n']}, просроченных дедлайнов: {due['n']}\nПоследний бэкап: {last_backup_info()}\n\n"
        f"<b>Последние ошибки:</b>\n{errs}")


# =====================================================================================
# 9. FLOW ROUTER, FALLBACKS, ERROR HANDLING, STARTUP
# =====================================================================================

fb_r = Router(name="fallback")


@flow_r.message(Flow.input)
async def on_flow(m: Message, state: FSMContext, role: str, db_user: dict):
    d = await state.get_data()
    ent = FLOWS.get(d.get("kind"))
    if not ent:
        await state.clear()
        return await m.answer("Сессия устарела. Начните действие заново.")
    fn, roles = ent
    if role not in roles:  # server-side role check for every flow step
        await state.clear()
        return await m.answer(NO_RIGHTS)
    await fn(m, state, d, role, db_user)


@fb_r.message(F.text)
async def fb_text(m: Message, role: str):
    await m.answer("Пожалуйста, используйте кнопки меню.", reply_markup=menu_for(role))


@fb_r.message()
async def fb_other(m: Message):
    await m.answer(RECEIPT_ONLY if m.content_type in {"video", "voice", "audio", "sticker", "animation", "video_note"}
                   else "Это сообщение не поддерживается. Используйте кнопки меню.")


@fb_r.callback_query()
async def fb_callback(cb: CallbackQuery):
    await cb.answer("Действие недоступно или устарело.", show_alert=True)


async def on_my_chat_member(ev) -> None:
    """Marks users who block the bot, so broadcasts skip them."""
    try:
        if ev.chat.type == "private" and ev.new_chat_member.status in ("kicked", "left"):
            await q_exec_simple("UPDATE users SET is_bot_blocked=true WHERE telegram_id=:t", t=ev.from_user.id)
        elif ev.chat.type == "private" and ev.new_chat_member.status == "member":
            await q_exec_simple("UPDATE users SET is_bot_blocked=false WHERE telegram_id=:t", t=ev.from_user.id)
    except Exception:
        log.exception("my_chat_member handling failed")


async def on_error(event: ErrorEvent) -> bool:
    log.error("Unhandled error: %r", event.exception, exc_info=event.exception)
    upd = event.update
    try:
        if upd.message:
            await upd.message.answer(ERR_TEXT)
        elif upd.callback_query:
            await upd.callback_query.answer(ERR_TEXT, show_alert=True)
    except Exception:
        pass
    return True


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    gate = Gate()
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    # order matters: staff and owner routers first, generic flow handler before fallbacks
    for r in (staff_r, owner_r, cust, flow_r, fb_r):
        dp.include_router(r)
    dp.my_chat_member.register(on_my_chat_member)
    dp.errors.register(on_error)
    return dp


async def resume_broadcasts(bot: Bot) -> None:
    for r in await fetchall("SELECT id FROM broadcasts WHERE status='SENDING'"):
        log.info("resuming broadcast %s", r["id"])
        spawn_broadcast(bot, r["id"])


async def main() -> None:
    try:
        cfg = load_config()
    except ConfigError as ex:
        print(f"CONFIGURATION ERROR: {ex}", flush=True)
        raise SystemExit(2)
    init_config(cfg)
    setup_logging()
    log.info("starting shop bot (timezone=%s, payment deadline=%s min)", cfg.tz_name, cfg.deadline_min)
    try:
        await init_db()
        await ensure_schema()
    except Exception:
        log.exception("database is not reachable or schema setup failed")
        raise SystemExit(3)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    tasks: list[asyncio.Task] = []
    try:
        me = await bot.get_me()  # validates the token
        log.info("bot authorised as @%s", me.username)
        dp = build_dispatcher()
        tasks = [asyncio.create_task(outbox_loop(bot)), asyncio.create_task(sweeper_loop(bot))]
        await resume_broadcasts(bot)
        # SIGINT/SIGTERM are handled by aiogram: polling stops gracefully, then the finally block runs
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        log.info("shutting down")
        for t in tasks + list(BG_TASKS):
            t.cancel()
        await asyncio.gather(*tasks, *BG_TASKS, return_exceptions=True)
        await bot.session.close()
        if ENGINE is not None:
            await ENGINE.dispose()


if __name__ == "__main__":
    asyncio.run(main())
