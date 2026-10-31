from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo)

import config
from db import database as db
from services.notify import notify_user
from services.subscription import missing_channels

router = Router()
WELCOME = ("👋 Здесь можно купить <b>Telegram Stars</b>, <b>Premium</b> и <b>NFT-подарки</b>. "
           "Оплата — картами Uzcard и Humo.\n\nОткройте магазин кнопкой ниже.")
GATE = "🔒 Чтобы пользоваться магазином, подпишитесь на каналы ниже и нажмите «Я подписался»."


async def _kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🛍 Открыть магазин", web_app=WebAppInfo(url=config.WEBAPP_URL))]]
    if url := await db.support_url():
        rows.append([InlineKeyboardButton(text="🛟 Поддержка", url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _gate_kb(missing: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['title']}", url=c["link"])] for c in missing if c.get("link")]
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _missing(bot: Bot, uid: int) -> list:
    return [] if uid in config.ADMIN_IDS else await missing_channels(bot, uid)


async def _bonus(bot: Bot, uid: int):
    """Реферальный бонус пригласившему — после прохождения проверки подписки."""
    if r := await db.grant_signup_bonus(uid):
        await notify_user(bot, r[0], f"🎉 Ваш друг присоединился по вашей ссылке — вам +{r[1]:,} сум".replace(",", " "))


@router.message(CommandStart())
async def start(m: Message, command: CommandObject, bot: Bot):
    is_new = await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    arg = command.args or ""
    if is_new and arg.startswith("ref_") and arg[4:].isdigit():
        await db.set_referrer(m.from_user.id, int(arg[4:]))
    if miss := await _missing(bot, m.from_user.id):
        return await m.answer(GATE, reply_markup=_gate_kb(miss))
    await _bonus(bot, m.from_user.id)
    await m.answer(WELCOME, reply_markup=await _kb())


@router.message(Command("help"))
async def help_(m: Message, bot: Bot):
    await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    if miss := await _missing(bot, m.from_user.id):
        return await m.answer(GATE, reply_markup=_gate_kb(miss))
    await m.answer(WELCOME, reply_markup=await _kb())


@router.callback_query(F.data == "sub:check")
async def sub_check(cb: CallbackQuery, bot: Bot):
    if await _missing(bot, cb.from_user.id):
        return await cb.answer("Вы подписаны не на все каналы", show_alert=True)
    await _bonus(bot, cb.from_user.id)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.message.answer(WELCOME, reply_markup=await _kb())
    await cb.answer()
