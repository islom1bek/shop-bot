"""Слушает сообщения @CardXabarBot в вашем Telegram-аккаунте (Telethon) и пересылает их в бэкенд.
Запуск (первый раз — интерактивно, для ввода кода входа):
    docker compose --profile listener run --rm listener
"""
import os

import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient, events

load_dotenv()
URL = os.getenv("WEBHOOK_URL", "http://bot:8080/webhook/cardxabar")
SECRET = os.environ["WEBHOOK_SECRET"]
os.makedirs("session", exist_ok=True)
client = TelegramClient("session/cardxabar", int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])


@client.on(events.NewMessage(from_users="CardXabarBot"))
async def on_msg(event):
    payload = {"id": f"{event.chat_id}:{event.id}", "text": event.raw_text or ""}
    async with aiohttp.ClientSession() as s:
        async with s.post(URL, json=payload, headers={"X-Webhook-Secret": SECRET}) as r:
            print(r.status, await r.text())


client.start()
print("Listening @CardXabarBot…")
client.run_until_disconnected()
