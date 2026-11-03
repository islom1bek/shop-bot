"""Один раз на СВОЁМ компьютере: получить строку TG_SESSION для Render.
    pip install telethon
    python parser/make_session.py
Спросит API ID, API HASH (my.telegram.org), номер телефона и код из Telegram.
Выведенную длинную строку вставьте в Render -> Environment -> TG_SESSION.
ВНИМАНИЕ: эта строка = полный доступ к вашему Telegram-аккаунту. Никому не показывайте, на GitHub не кладите."""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("API ID: ").strip())
api_hash = input("API HASH: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nВот ваша TG_SESSION (скопируйте целиком):\n")
    print(client.session.save())
