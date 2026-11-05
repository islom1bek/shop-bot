import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import i18n
from db import database as db


async def notify_user(bot: Bot, uid: int, text: str):
    try:
        await bot.send_message(uid, text)
    except Exception as e:
        logging.warning("notify_user %s: %s", uid, e)


async def notify_t(bot: Bot, uid: int, key: str, **kw):
    """Foydalanuvchiga uning tilida xabar (i18n.TEXTS[key])."""
    lang = await db.get_lang(uid)
    await notify_user(bot, uid, i18n.t(lang, key, **kw))


async def notify_admins(bot: Bot, text: str, kb: InlineKeyboardMarkup | None = None):
    for a in config.ADMIN_IDS:
        try:
            await bot.send_message(a, text, reply_markup=kb)
        except Exception as e:
            logging.warning("notify_admin %s: %s", a, e)


def order_kb(oid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выдан", callback_data=f"ordn:done:{oid}"),
        InlineKeyboardButton(text="❌ Отклонить и вернуть", callback_data=f"ordn:refund:{oid}")]])
