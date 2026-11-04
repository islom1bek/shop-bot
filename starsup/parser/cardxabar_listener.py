"""Слушает сообщения @CardXabarBot в вашем Telegram-аккаунте (Telethon) и пересылает их боту.

Два режима:
1) ВНУТРИ бота (Render и т.п.): в .env задана TG_SESSION — main.py сам запускает слушатель, отдельный сервис не нужен.
   Строку TG_SESSION получают один раз на своём компьютере:  python parser/make_session.py
2) ОТДЕЛЬНО (docker compose --profile listener ...): файловая сессия, первый вход интерактивно.

При старте делает самодиагностику (под каким аккаунтом вошли, виден ли CardXabarBot, жив ли бот).
DEBUG_ALL=1 в .env — печатать все входящие сообщения и от кого (для поиска неверного имени бота).
"""
import asyncio
import os
from urllib.parse import urlsplit

import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

load_dotenv()


def _client() -> TelegramClient:
    api_id, api_hash = int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]
    if s := os.getenv("TG_SESSION", "").strip():
        return TelegramClient(StringSession(s), api_id, api_hash)
    os.makedirs("session", exist_ok=True)
    return TelegramClient("session/cardxabar", api_id, api_hash)


async def _send(url: str, secret: str, payload: dict):
    for attempt in range(5):                     # бот может ещё стартовать — повторяем
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.post(url, json=payload, headers={"X-Webhook-Secret": secret}) as r:
                    print("webhook ->", r.status, await r.text(), flush=True)
                    if r.status < 500:
                        return r.status
        except Exception as ex:
            print("webhook error:", ex, flush=True)
        await asyncio.sleep(3 * (attempt + 1))


async def _selfcheck(client, url: str, source: str) -> tuple[str, bool]:
    """-> (текст отчёта, всё ли хорошо)"""
    me = await client.get_me()
    lines, good = [f"вошли как: {me.first_name} @{me.username} (id {me.id})"], True
    try:
        src = await client.get_entity(source)
        last = await client.get_messages(src, limit=1)
        lines.append(f"@{source} найден" + (f"; последнее сообщение: {(last[0].raw_text or '')[:40]!r}" if last else "; переписка пуста"))
    except Exception as ex:
        good = False
        lines.append(f"❌ НЕ ВИЖУ @{source} в этом аккаунте ({ex}). Вошли не в тот аккаунт, нет чата с ботом "
                     f"или имя другое (CARDXABAR_USERNAME)")
    health = urlsplit(url)._replace(path="/health", query="").geturl()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.get(health) as r:
                lines.append(f"бот по {health}: HTTP {r.status}" + ("" if r.status == 200 else " ❌"))
                good &= r.status == 200
    except Exception as ex:
        good = False
        lines.append(f"❌ бот недоступен по {health}: {ex}")
    return "\n".join(lines), good


async def run_forever(url: str, secret: str, report=None):
    """Подключается, печатает диагностику, слушает. Исключение — если не удалось войти (сессия недействительна)."""
    source = os.getenv("CARDXABAR_USERNAME", "CardXabarBot")
    debug = os.getenv("DEBUG_ALL") == "1"
    client = _client()
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram-сессия недействительна — создайте новую TG_SESSION (python parser/make_session.py)")

    @client.on(events.NewMessage(incoming=True))
    async def on_msg(event):
        sender = await event.get_sender()
        uname = (getattr(sender, "username", None) or "").lower()
        if debug:
            print(f"[debug] от @{uname or getattr(sender, 'id', '?')}: {(event.raw_text or '')[:60]!r}", flush=True)
        if uname != source.lower():
            return
        print("CardXabar:", (event.raw_text or "")[:80].replace("\n", " | "), flush=True)
        await _send(url, secret, {"id": f"{event.chat_id}:{event.id}", "text": event.raw_text or ""})

    text, good = await _selfcheck(client, url, source)
    print("[check]", text, flush=True)
    if report:
        await report(("✅ " if good else "⚠️ ") + "CardXabar listener запущен\n" + text)
    print(f"Listening @{source}…", flush=True)
    await client.run_until_disconnected()


async def _standalone():
    await run_forever(os.getenv("WEBHOOK_URL", "http://bot:8080/webhook/cardxabar"), os.environ["WEBHOOK_SECRET"])


if __name__ == "__main__":
    asyncio.run(_standalone())
