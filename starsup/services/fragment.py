"""Выдача Stars / Premium через Fragment, оплата с вашего TON-кошелька.

У Fragment НЕТ официального API. Модуль повторяет запросы сайта fragment.com/api от вашей
авторизованной сессии (cookies + hash) и отправляет TON-транзакцию с payload, который вернул Fragment.
Это неофициальный путь: Fragment может изменить запросы или сбросить сессию — тогда заказы
не будут выдаваться, а админ получит алерт (см. FragmentAuthError).

Контракт как у services.fulfillment._http: возвращает ('ok', ref) | ('fail', причина) | ('unknown', причина).
  fail    — деньги TON ещё НЕ отправлены, товар точно не выдан  -> авто-возврат клиенту
  unknown — TON мог уйти (или ответ неясен)                       -> заказ 'review', решает админ
"""
import asyncio
import base64
import json
import logging
import re

import aiohttp

import config

API = "https://fragment.com/api"
TIMEOUT = aiohttp.ClientTimeout(total=30)
DEVICE = {"platform": "web", "appName": "tonkeeper", "appVersion": "3.0.0", "maxProtocolVersion": 2,
          "features": ["SendTransaction", {"name": "SendTransaction", "maxMessages": 4}]}

_wallet_lock = asyncio.Lock()       # TON-кошелёк шлёт транзакции строго по одной (seqno)
_wallet = None
_provider = None


class FragmentAuthError(Exception):
    """Сессия Fragment протухла: обновите FRAGMENT_COOKIES / FRAGMENT_HASH."""


class FragmentFail(Exception):
    """Fragment отказал ДО отправки TON (неверный @username, нет такого пакета и т.п.)."""


def configured() -> bool:
    return bool(config.FRAGMENT_HASH and config.FRAGMENT_COOKIES and config.TON_MNEMONIC)


# ------------------------------------------------------------------ TON-кошелёк
async def _get_wallet():
    global _wallet, _provider
    if _wallet is None:
        from pytoniq import LiteBalancer, WalletV4R2          # импорт здесь: модуль нужен только при Fragment
        _provider = LiteBalancer.from_mainnet_config(trust_level=2)
        await _provider.start_up()
        _wallet = await WalletV4R2.from_mnemonic(_provider, config.TON_MNEMONIC.split())
    return _wallet


async def wallet_info() -> dict:
    """Адрес и баланс TON для /fragment в админке."""
    w = await _get_wallet()
    bal = await w.get_balance()
    return {"address": w.address.to_str(is_user_friendly=True, is_bounceable=False), "ton": bal / 1e9}


async def _account() -> dict:
    w = await _get_wallet()
    return {"address": w.address.to_str(is_user_friendly=False), "chain": "-239",
            "walletStateInit": base64.b64encode(w.state_init.serialize().to_boc()).decode(),
            "publicKey": w.public_key.hex() if isinstance(w.public_key, (bytes, bytearray)) else str(w.public_key)}


# ------------------------------------------------------------------ Fragment web API
async def _api(session: aiohttp.ClientSession, method: str, **data) -> dict:
    async with session.post(f"{API}?hash={config.FRAGMENT_HASH}", data={"method": method, **data}) as r:
        if r.status in (401, 403):
            raise FragmentAuthError(f"{method}: Fragment вернул {r.status}")
        if r.status >= 500:
            raise aiohttp.ClientError(f"{method}: Fragment {r.status}")
        raw = await r.text()
    try:
        j = json.loads(raw)
    except ValueError:
        raise FragmentFail(f"{method}: Fragment вернул не JSON (HTTP {r.status}): {raw[:150]!r}")
    if not isinstance(j, dict):
        raise aiohttp.ClientError(f"{method}: странный ответ Fragment")
    if j.get("error"):
        err = str(j["error"])
        logging.warning("fragment %s -> error=%r, полный ответ: %s", method, err, raw[:500])
        if "auth" in err.lower() or "login" in err.lower() or "session" in err.lower():
            raise FragmentAuthError(f"{method}: {err}")
        raise FragmentFail(f"{method}: {err}")
    return j


async def check_session() -> str:
    """Диагностика для /fragment: авторизована ли сессия и подходит ли hash. Ничего не покупает."""
    lines = []
    async with aiohttp.ClientSession(timeout=TIMEOUT, headers=_headers()) as s:
        async with s.get("https://fragment.com/stars/buy") as r:
            html = await r.text()
            lines.append(f"Страница stars/buy: HTTP {r.status}")
    m = re.search(r'"apiUrl"\s*:\s*"\\?/api\?hash=([0-9a-f]+)"', html)
    page_hash = m.group(1) if m else None
    lines.append(f"unauth на странице: {'ДА ❌ (cookies не авторизованы)' if '\"unauth\":true' in html else 'нет ✅'}")
    lines.append(f"hash на странице: {page_hash or 'не найден'}")
    lines.append(f"hash в .env: {config.FRAGMENT_HASH} → {'совпадает ✅' if page_hash == config.FRAGMENT_HASH else 'НЕ совпадает ❌'}")
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT, headers=_headers()) as s:
            j = await _api(s, "searchStarsRecipient", query="durov", quantity=50)
        lines.append(f"searchStarsRecipient: ok={bool(j.get('found'))}")
    except Exception as ex:
        lines.append(f"searchStarsRecipient: ошибка {ex}")
    try:
        w = await _get_wallet()
        lines.append("Кошелёк (raw): " + w.address.to_str(is_user_friendly=False))
    except Exception as ex:
        lines.append(f"кошелёк: ошибка {ex}")
    return "\n".join(lines)


def _headers() -> dict:
    return {"Cookie": config.FRAGMENT_COOKIES, "Origin": "https://fragment.com",
            "Referer": "https://fragment.com/stars/buy", "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


async def _prepare(kind: str, username: str, qty: int) -> tuple[str, dict]:
    """-> (req_id, transaction) — всё до отправки денег. Ошибка здесь = точно не выдано."""
    username = username.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", username):
        raise FragmentFail("у клиента нет корректного @username")
    account = await _account()
    async with aiohttp.ClientSession(timeout=TIMEOUT, headers=_headers()) as s:
        if kind == "stars":
            found = await _api(s, "searchStarsRecipient", query=username, quantity=qty)
            init = await _api(s, "initBuyStarsRequest", recipient=found["found"]["recipient"], quantity=qty)
            link = "getBuyStarsLink"
        else:
            found = await _api(s, "searchPremiumGiftRecipient", query=username, months=qty)
            init = await _api(s, "initGiftPremiumRequest", recipient=found["found"]["recipient"], months=qty)
            link = "getGiftPremiumLink"
        req_id = init["req_id"]
        tx = await _api(s, link, id=req_id, show_sender=0, transaction=1,
                        account=json.dumps(account), device=json.dumps(DEVICE))
    msgs = (tx.get("transaction") or {}).get("messages") or []
    if len(msgs) != 1:
        raise FragmentFail(f"Fragment вернул неожиданную транзакцию: {str(tx)[:200]}")
    return req_id, msgs[0]


async def _pay(msg: dict):
    """Отправка TON. После успешной отправки считаем, что деньги ушли."""
    from pytoniq import Address, Cell
    w = await _get_wallet()
    body = Cell.one_from_boc(base64.b64decode(msg["payload"] + "=" * (-len(msg["payload"]) % 4)))
    await w.transfer(destination=Address(msg["address"]), amount=int(msg["amount"]), body=body)


async def buy(kind: str, username: str, qty: int, order_id: int):
    """kind: 'stars' | 'premium'. qty: число звёзд или месяцев."""
    if not configured():
        return "fail", "Fragment не настроен (FRAGMENT_HASH / FRAGMENT_COOKIES / TON_MNEMONIC)"
    async with _wallet_lock:
        try:
            req_id, msg = await _prepare(kind, username, qty)
            ton_cost = int(msg["amount"]) / 1e9
            if ton_cost > config.FRAGMENT_MAX_TON:                  # защита от аномально дорогого заказа
                return "fail", f"стоимость {ton_cost:.2f} TON выше лимита FRAGMENT_MAX_TON"
            w = await _get_wallet()
            if await w.get_balance() < int(msg["amount"]) + 50_000_000:     # +0.05 TON на комиссию
                return "fail", f"не хватает TON на кошельке (нужно ≈{ton_cost:.2f})"
        except FragmentAuthError as ex:
            return "fail", f"сессия Fragment недействительна — обновите cookies/hash ({ex})"
        except FragmentFail as ex:
            return "fail", f"Fragment: {ex}"
        except (KeyError, TypeError) as ex:
            return "fail", f"Fragment изменил формат ответа ({ex!r})"
        except (asyncio.TimeoutError, aiohttp.ClientError) as ex:
            return "fail", f"нет связи с Fragment до оплаты: {ex}"     # деньги ещё не отправлены
        try:
            await _pay(msg)
        except Exception as ex:                                        # неясно, ушла ли транзакция
            logging.exception("TON transfer #%s", order_id)
            return "unknown", f"ошибка при отправке TON (проверьте кошелёк): {ex}"
    logging.info("fragment #%s: %s %s -> @%s, %.3f TON, req %s", order_id, kind, qty, username, ton_cost, req_id)
    return "ok", f"fragment:{req_id}:{ton_cost:.3f}TON"
