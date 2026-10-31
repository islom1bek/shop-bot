from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo)

import config
from db import database as db

router = Router()


async def _kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🛍 Открыть магазин", web_app=WebAppInfo(url=config.WEBAPP_URL))]]
    if url := await db.support_url():
        rows.append([InlineKeyboardButton(text="🛟 Поддержка", url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
@router.message(Command("help"))
async def start(m: Message):
    await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    await m.answer("👋 Здесь можно купить <b>Telegram Stars</b>, <b>Premium</b> и <b>NFT-подарки</b>. "
                   "Оплата — картами Uzcard и Humo.\n\nОткройте магазин кнопкой ниже.", reply_markup=await _kb())
