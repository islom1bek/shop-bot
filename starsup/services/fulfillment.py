"""Автовыдача: вызывается сразу после списания баланса (db.purchase), в фоне.

Поток:  purchase() [списание, FOR UPDATE, COMMIT] -> schedule() -> process_order():
  claim (processing -> delivering, атомарно) -> выдача -> done | refund | review

Результат выдачи бывает трёх видов (важно для денег):
  ok      — товар выдан                       -> заказ 'done'
  fail    — ТОЧНО не выдан (отказ API)        -> авто-возврат на баланс
  unknown — неясно (таймаут, 5xx, рестарт)    -> заказ 'review', деньги удерживаются, админу алерт.
            Авто-возврат тут опасен: товар мог дойти, и вы заплатите дважды.
Идемпотентность: провайдеру уходит external_id = order-<id>, а claim исключает двойную выдачу.
"""
import asyncio
import logging
import time

import aiohttp

import config
from db import database as db
from services import fragment
import i18n
from services.notify import notify_admins, notify_t

# Цены Bot API giftPremiumSubscription (Stars с баланса бота). Сверяйте с core.telegram.org/bots/api
PREMIUM_STARS = {3: 1000, 6: 1500, 12: 2500}
TIMEOUT = aiohttp.ClientTimeout(total=30)
_tasks: set = set()


async def _ltitle(uid: int, title: str) -> str:
    """Mahsulot nomi foydalanuvchi tilida."""
    return i18n.loc_title(title, await db.get_lang(uid))


def _sum(n) -> str:
    return f"{int(n):,}".replace(",", " ")


# ---------------------------------------------------------------- Telegram Bot API
async def tg_call(method: str, **params):
    """-> ('ok', result) | ('fail', причина) | ('unknown', причина)"""
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}"
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
                async with s.post(url, json=params) as r:
                    data = await r.json(content_type=None)
        except aiohttp.ClientConnectorError as e:
            return "fail", f"нет соединения с Telegram: {e}"
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as e:
            return "unknown", f"сбой сети/ответа Telegram: {e}"
        if data.get("ok"):
            return "ok", data.get("result")
        code = int(data.get("error_code", 0))
        if code == 429 and attempt < 2:
            await asyncio.sleep(int(data.get("parameters", {}).get("retry_after", 2)) + 1)
            continue
        if code >= 500 or code == 0:
            return "unknown", f"{code}: {data.get('description')}"
        return "fail", f"{code}: {data.get('description')}"
    return "fail", "429 Too Many Requests"


# ---------------------------------------------------------------- HTTP-провайдер (Fragment-шлюз)
def _state(d) -> str:
    if not isinstance(d, dict):
        return "pending"
    s = str(d.get("status") or ("completed" if (d.get("ok") or d.get("success")) else "")).lower()
    if s in ("completed", "complete", "success", "succeeded", "done", "delivered", "ok"):
        return "ok"
    if s in ("failed", "fail", "error", "cancelled", "canceled", "rejected", "refunded"):
        return "fail"
    return "pending"


async def _http(path: str, payload: dict, order_id: int):
    """ШАБЛОН под API вашего провайдера: подправьте поля запроса/ответа под его документацию.
    Ожидает: POST {PROVIDER_URL}{path} -> JSON со status (completed|pending|failed) и id;
    для pending опрашивает GET {PROVIDER_URL}{PROVIDER_STATUS_PATH}."""
    if not (config.PROVIDER_URL and config.PROVIDER_TOKEN):
        return "fail", "провайдер не настроен (PROVIDER_URL / PROVIDER_TOKEN)"
    ext = f"order-{order_id}"
    headers = {"Authorization": f"Bearer {config.PROVIDER_TOKEN}", "Idempotency-Key": ext}
    sent = False                                   # после отправки запроса сеть уже не гарантирует «не выдано»
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT, headers=headers) as s:
            async with s.post(config.PROVIDER_URL + path, json={**payload, "external_id": ext}) as r:
                sent = True
                status, data = r.status, await r.json(content_type=None)
            if status >= 500 or status in (408, 409):
                return "unknown", f"провайдер ответил {status}: {str(data)[:200]}"
            if status >= 400:
                return "fail", f"провайдер отклонил запрос ({status}): {str(data)[:200]}"
            st = _state(data)
            ref = str((data.get("id") or data.get("request_id") or data.get("transaction_id")) if isinstance(data, dict) else "") or ext
            if st == "ok":
                return "ok", ref
            if st == "fail":
                return "fail", f"провайдер: {str(data)[:200]}"
            deadline = time.monotonic() + config.PROVIDER_POLL_SECONDS
            while time.monotonic() < deadline:                       # заказ в очереди провайдера — ждём
                await asyncio.sleep(5)
                async with s.get(config.PROVIDER_URL + config.PROVIDER_STATUS_PATH.format(id=ref)) as r2:
                    d2 = await r2.json(content_type=None)
                st = _state(d2)
                if st == "ok":
                    return "ok", ref
                if st == "fail":
                    return "fail", f"провайдер: {str(d2)[:200]}"
            return "unknown", f"провайдер не завершил заказ за {config.PROVIDER_POLL_SECONDS} с (ref {ref})"
    except aiohttp.ClientConnectorError as e:
        return ("unknown" if sent else "fail"), f"нет соединения с провайдером: {e}"
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as e:
        return "unknown", f"сбой сети/ответа провайдера: {e}"


# ---------------------------------------------------------------- проверка ДО списания денег
async def preflight(product: dict, user: dict, recipient: str | None = None):
    off = db.BotError("service_disabled", db.SERVICE_DISABLED)
    cat, qty = product["category"], product["qty"]
    if await db.get_setting(f"enabled_{cat}") != "1":      # тумблер товара выключен
        raise off
    if cat == "gifts":
        if not product["gift_id"]:
            raise off
    elif cat == "premium" and config.PREMIUM_MODE == "telegram":
        if qty not in PREMIUM_STARS:
            raise off
    else:                                           # Stars и Premium через Fragment или провайдера
        via_fragment = (cat == "stars" and config.STARS_MODE == "fragment") or \
                       (cat == "premium" and config.PREMIUM_MODE == "fragment")
        if not qty or not (fragment.configured() if via_fragment else (config.PROVIDER_URL and config.PROVIDER_TOKEN)):
            raise off
        if not (recipient or user.get("username")):
            raise db.BotError("no_username", "Для этого товара нужен @username: задайте его в настройках Telegram и повторите")


async def _deliver(order: dict, product: dict, user: dict):
    cat, qty = order["category"], product["qty"]
    rcp = order.get("recipient") or user.get("username")        # @username получателя (себе или другу)
    target = order.get("rcp_id") or order["user_id"]            # tg_id получателя для Bot API (по умолчанию — покупатель)
    note = (order.get("note") or "").strip()[:128]              # комментарий покупателя к подарку
    if cat == "gifts":
        return await tg_call("sendGift", user_id=target, gift_id=product["gift_id"],
                             text=note or i18n.t(user.get("lang"), "thanks_gift"))
    if cat == "premium" and config.PREMIUM_MODE == "telegram":
        return await tg_call("giftPremiumSubscription", user_id=target, month_count=qty,
                             star_count=PREMIUM_STARS[qty], text=note or i18n.t(user.get("lang"), "thanks_premium"))
    if cat == "premium":
        if config.PREMIUM_MODE == "fragment":
            return await fragment.buy("premium", rcp, qty, order["id"])
        return await _http(config.PROVIDER_PREMIUM_PATH, {"username": rcp, "months": qty}, order["id"])
    if config.STARS_MODE == "fragment":
        return await fragment.buy("stars", rcp, qty, order["id"])
    return await _http(config.PROVIDER_STARS_PATH, {"username": rcp, "amount": qty}, order["id"])


# ---------------------------------------------------------------- обработка заказа
def schedule(bot, order_id: int):
    t = asyncio.create_task(process_order(bot, order_id))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def process_order(bot, order_id: int):
    order = await db.claim_order(order_id)          # атомарно: второй вызов получит None
    if not order:
        return
    try:
        product = await db.get_product(order["product_id"]) if order["product_id"] else None
        if not product:                                  # своё кол-во Stars (без товара в каталоге) — берём из заказа
            product = {"category": order["category"], "qty": order.get("qty"), "gift_id": None}
        user = await db.get_user(order["user_id"])
        result, info = await _deliver(order, product, user)
    except Exception as ex:
        logging.exception("fulfillment #%s crashed", order_id)
        result, info = "unknown", f"исключение: {ex}"
    title, uid, oid = order["title"], order["user_id"], order_id
    try:
        if result == "ok":
            await db.order_action(oid, "done", allowed=("delivering", "review"), ref=str(info)[:200])
            await notify_t(bot, uid, "order_done", id=oid, title=await _ltitle(uid, title))
            if str(info).startswith("fragment:"):
                await _low_ton_alert(bot)
        elif result == "fail":
            await db.order_action(oid, "refund", allowed=("delivering", "review"), error=str(info)[:300])
            await notify_t(bot, uid, "order_refund", id=oid, title=await _ltitle(uid, title), amt=_sum(order["price"]))
            await notify_admins(bot, f"⚠️ Автовыдача #{oid} не удалась, деньги возвращены клиенту.\nПричина: {info}")
        else:
            await db.order_action(oid, "review", allowed=("delivering",), error=str(info)[:300])
            await notify_t(bot, uid, "order_review", id=oid, title=await _ltitle(uid, title))
            await notify_admins(bot, f"🔎 Заказ #{oid} требует проверки (клиент {uid}, {title}, {_sum(order['price'])} сум).\n"
                                     f"Причина: {info}\nПроверьте у провайдера, затем: /done {oid} (выдано) или /refund {oid} (вернуть).")
    except db.BotError as ex:
        logging.warning("settle #%s: %s", oid, ex.message)


async def _low_ton_alert(bot):
    try:
        w = await fragment.wallet_info()
        if w["ton"] < config.FRAGMENT_LOW_TON:
            await notify_admins(bot, f"⚠️ На TON-кошельке Fragment осталось {w['ton']:.2f} TON. Пополните: <code>{w['address']}</code>")
    except Exception as ex:
        logging.warning("low-ton check: %s", ex)


async def recover_stuck(bot):
    """При старте: 'delivering' (процесс упал в момент выдачи) -> 'review'; 'processing' -> выдать заново."""
    for o in await db.stuck_orders():
        try:
            if o["status"] == "delivering":
                await db.order_action(o["id"], "review", allowed=("delivering",),
                                      error="перезапуск процесса во время выдачи — проверьте вручную")
                await notify_admins(bot, f"🔎 Заказ #{o['id']}: процесс перезапускался во время выдачи. "
                                         f"Проверьте, получил ли клиент товар: /done {o['id']} или /refund {o['id']}.")
            else:
                schedule(bot, o["id"])
        except db.BotError:
            pass
