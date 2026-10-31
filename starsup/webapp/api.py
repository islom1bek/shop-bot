"""HTTP-слой: отдаёт Mini App, JSON API и вебхук от парсера @CardXabarBot."""
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qsl

from aiohttp import web

import config
from db import database as db
from services.notify import notify_admins, notify_user, order_kb
from services.subscription import missing_channels
from services.payments import parse_amount

HERE = os.path.dirname(__file__)
DESIGN = os.path.join(HERE, "design")          # весь внешний вид Mini App — в этой папке
DESIGN_EXT = {".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".woff", ".woff2", ".ico"}


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    return str(o)


def ok(**data):
    return web.json_response({"ok": True, **data}, dumps=lambda o: json.dumps(o, default=_default))


def err(code: str, message: str, status: int = 400):
    return web.json_response({"ok": False, "error": code, "message": message}, status=status)


def clean(row) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(row).items()}


def validate_init_data(init_data: str, max_age: int = 86400) -> dict | None:
    """Проверка подписи Telegram WebApp initData."""
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        got = parsed.pop("hash", None)
        check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not got or not hmac.compare_digest(calc, got):
            return None
        if time.time() - int(parsed.get("auth_date", 0)) > max_age:
            return None
        return json.loads(parsed["user"])
    except Exception:
        return None


async def current_user(request) -> dict:
    user = validate_init_data(request.headers.get("X-Init-Data", ""))
    if not user:
        raise db.BotError("auth", "Откройте магазин через Telegram")
    await db.upsert_user(user["id"], user.get("username"), user.get("first_name"))
    if user["id"] not in config.ADMIN_IDS:            # обязательная подписка (админы — без проверки)
        if miss := await missing_channels(request.app["bot"], user["id"]):
            raise NotSubscribed(miss)
    return user


class NotSubscribed(db.BotError):
    def __init__(self, channels):
        super().__init__("not_subscribed", "Подпишитесь на каналы, чтобы пользоваться магазином")
        self.channels = [{"title": c["title"], "link": c.get("link")} for c in channels]


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ")


DEFAULT_REF_TEXT = ("Sizning havolangizdan yangi do'stingiz tashrif buyursa {bonus} so'm bonus olasiz va "
                    "do'stlaringizning har bir hisob to'ldirishidan {percent}% ulush olasiz")


async def bot_username(app) -> str:
    if "bot_username" not in app:
        app["bot_username"] = (await app["bot"].get_me()).username
    return app["bot_username"]


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except NotSubscribed as e:
        return web.json_response({"ok": False, "error": e.code, "message": e.message, "channels": e.channels})
    except db.BotError as e:
        return err(e.code, e.message, 401 if e.code == "auth" else 400)
    except web.HTTPException:
        raise
    except Exception:
        logging.exception("API error")
        return err("server", "Ошибка сервера. Попробуйте позже", 500)


routes = web.RouteTableDef()


@routes.get("/")
async def index(request):
    return web.FileResponse(os.path.join(DESIGN, "index.html"), headers={"Cache-Control": "no-cache"})


@routes.get("/static/{name}")
async def static(request):
    name = request.match_info["name"]
    if name == "app.js":                               # логика (не дизайн)
        path = os.path.join(HERE, "app.js")
    elif os.path.splitext(name)[1].lower() in DESIGN_EXT:   # стили и картинки из design/
        path = os.path.join(DESIGN, name)
    else:
        raise web.HTTPNotFound()
    if not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-cache"})


@routes.get("/health")
async def health(request):
    return ok()


@routes.get("/api/bootstrap")
async def bootstrap(request):
    u = await current_user(request)
    if r := await db.grant_signup_bonus(u["id"]):      # бонус пригласившему после проверки подписки
        await notify_user(request.app["bot"], r[0], f"🎉 Ваш друг присоединился — вам +{fmt(r[1])} сум")
    s = await db.get_settings()
    orders = await db.pool.fetch("SELECT id,title,price,recipient,status,created_at FROM orders "
                                 "WHERE user_id=$1 ORDER BY id DESC LIMIT 30", u["id"])
    topups = await db.pool.fetch("SELECT id,amount,method,status,created_at FROM topups "
                                 "WHERE user_id=$1 ORDER BY id DESC LIMIT 30", u["id"])
    return ok(
        user={"id": u["id"], "name": u.get("first_name") or "Друг", "username": u.get("username"),
              "balance": await db.get_balance(u["id"])},
        support=await db.support_url(),
        toggles={"stars": s["enabled_stars"] == "1", "premium": s["enabled_premium"] == "1",
                 "gifts": s["enabled_gifts"] == "1", "uzcard": s["pay_uzcard"] == "1", "humo": s["pay_humo"] == "1"},
        limits={"min": int(s["topup_min"]), "max": int(s["topup_max"])},
        products=await db.catalog(),
        orders=[clean(r) for r in orders], topups=[clean(r) for r in topups])


@routes.post("/api/topup")
async def create_topup(request):
    u = await current_user(request)
    body = await request.json()
    method, s = body.get("method"), await db.get_settings()
    if method not in ("uzcard", "humo"):
        return err("bad_request", "Выберите способ оплаты")
    card = s[f"card_{method}"].strip()
    if s[f"pay_{method}"] != "1" or not card:
        return err("service_disabled", db.SERVICE_DISABLED)
    try:
        amount = int(body.get("amount"))
    except (TypeError, ValueError):
        return err("bad_request", "Введите сумму числом")
    lo, hi = int(s["topup_min"]), int(s["topup_max"])
    if not lo <= amount <= hi:
        return err("bad_amount", f"Сумма пополнения: от {lo:,} до {hi:,} сум".replace(",", " "))
    t = await db.create_topup(u["id"], amount, method)
    return ok(topup={**clean(t), "card": card, "holder": s["card_holder"]})


@routes.get("/api/topup/{id}")
async def topup_status(request):
    u = await current_user(request)
    t = await db.pool.fetchrow("SELECT id,status,amount FROM topups WHERE id=$1 AND user_id=$2",
                               int(request.match_info["id"]), u["id"])
    if not t:
        return err("not_found", "Платёж не найден")
    return ok(status=t["status"], balance=await db.get_balance(u["id"]))


@routes.post("/api/buy")
async def buy(request):
    u = await current_user(request)
    body = await request.json()
    recipient = str(body.get("recipient") or u.get("username") or "").strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", recipient):
        return err("bad_recipient", "Укажите @username получателя (латиница, цифры, _)")
    order, balance = await db.purchase(u["id"], int(body.get("product_id", 0)), recipient)
    await notify_admins(
        request.app["bot"],
        f"🛒 <b>Новый заказ #{order['id']}</b>\n{order['title']} — {order['price']:,} сум\n"
        f"Покупатель: {u['id']} (@{u.get('username') or '—'})\nПолучатель: @{recipient}".replace(",", " "),
        order_kb(order["id"]))
    return ok(order=clean(order), balance=balance)


@routes.get("/api/referrals")
async def referrals(request):
    u = await current_user(request)
    s = await db.get_settings()
    stats = await db.referral_stats(u["id"])
    text = (s["ref_text"].strip() or DEFAULT_REF_TEXT).replace("{bonus}", fmt(s["ref_signup_bonus"])) \
        .replace("{percent}", str(s["ref_percent"]))
    return ok(link=f"https://t.me/{await bot_username(request.app)}?start=ref_{u['id']}", text=text,
              invited=stats["invited"], earned=stats["earned"], friends=[clean(f) for f in stats["friends"]])


@routes.post("/webhook/cardxabar")
async def cardxabar(request):
    """Парсер шлёт: {"id": "<уник. id сообщения>", "text": "<текст уведомления>"} (или готовый "amount")."""
    if not hmac.compare_digest(request.headers.get("X-Webhook-Secret", ""), config.WEBHOOK_SECRET):
        return err("forbidden", "bad secret", 403)
    data = await request.json()
    text = str(data.get("text", ""))
    amount = int(data["amount"]) if data.get("amount") else parse_amount(text)
    if not amount:
        return ok(status="ignored")
    key = hashlib.sha256(str(data.get("id") or text).encode()).hexdigest()
    status, t = await db.match_payment(amount, key, text)
    bot = request.app["bot"]
    if status == "matched":
        await notify_user(bot, t["user_id"], f"✅ Баланс пополнен на {t['amount']:,} сум.\n"
                          f"Текущий баланс: {t['balance']:,} сум".replace(",", " "))
        if t.get("ref"):
            await notify_user(bot, t["ref"][0], f"🎉 Ваш друг пополнил баланс — вам +{fmt(t['ref'][1])} сум")
    elif status == "unmatched":
        await notify_admins(bot, f"⚠️ Неопознанное поступление {amount:,} сум — нет ожидающего платежа с такой "
                            f"суммой.\nЕсли это клиент: /credit &lt;tg_id&gt; {amount}".replace(",", " "))
    return ok(status=status)


def create_app(bot) -> web.Application:
    app = web.Application(middlewares=[errors])
    app["bot"] = bot
    app.add_routes(routes)
    return app
