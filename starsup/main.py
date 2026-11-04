import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web

import config
from db import database as db
from handlers import admin, user
from services.fulfillment import recover_stuck
from services.notify import notify_admins
from webapp.api import create_app


async def run_listener(bot):
    """CardXabar listener внутри этого же процесса (если задан TG_SESSION): отдельный сервис не нужен."""
    await asyncio.sleep(3)                      # дать веб-серверу подняться
    try:
        from parser import cardxabar_listener as L
        await L.run_forever(f"http://127.0.0.1:{config.PORT}/webhook/cardxabar", config.WEBHOOK_SECRET,
                            report=lambda t: notify_admins(bot, t))
    except Exception as ex:
        logging.exception("listener")
        await notify_admins(bot, f"❌ CardXabar listener не работает: {ex}")


async def main():
    logging.basicConfig(level=logging.INFO)
    await db.init(config.DATABASE_URL)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await recover_stuck(bot)             # заказы, прерванные рестартом, не теряются
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)      # админ первым: у него фильтр по ID
    dp.include_router(user.router)

    runner = web.AppRunner(create_app(bot))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()

    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Do'kon · Магазин", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    await bot.delete_webhook(drop_pending_updates=True)
    if config.TG_SESSION:
        logging.info("CardXabar listener: ВКЛЮЧЁН (TG_SESSION задан) — запускаю")
        asyncio.create_task(run_listener(bot))
    else:
        logging.warning("CardXabar listener: ВЫКЛЮЧЕН — в Environment нет TG_SESSION, платежи приниматься не будут")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
