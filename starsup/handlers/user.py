from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message,
                           WebAppInfo)

import config
import i18n
from db import database as db
from i18n import t
from services.banner import send_card
from services.notify import notify_t
from services.subscription import missing_channels

router = Router()


# ---------------------------------------------------------------- klaviaturalar
def _lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")]])


async def _kb(lang: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t(lang, "btn_open"), web_app=WebAppInfo(url=config.WEBAPP_URL))]]
    if url := await db.support_url():
        rows.append([InlineKeyboardButton(text=t(lang, "btn_support"), url=url)])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="lang:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _gate_kb(missing: list, lang: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['title']}", url=c["link"])] for c in missing if c.get("link")]
    rows.append([InlineKeyboardButton(text=t(lang, "btn_subbed"), callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _missing(bot: Bot, uid: int) -> list:
    return [] if uid in config.ADMIN_IDS else await missing_channels(bot, uid)


async def _bonus(bot: Bot, uid: int):
    """Referal bonus taklif qilgan odamga — obuna tekshiruvidan o'tgandan keyin."""
    if r := await db.grant_signup_bonus(uid):
        await notify_t(bot, r[0], "ref_joined", amt=i18n.num(r[1]))


async def _set_menu_button(bot: Bot, uid: int, lang: str):
    """Chatdagi menyu tugmasi matni foydalanuvchi tilida (Do'kon / Магазин)."""
    try:
        await bot.set_chat_menu_button(chat_id=uid, menu_button=MenuButtonWebApp(
            text=t(lang, "menu_btn"), web_app=WebAppInfo(url=config.WEBAPP_URL)))
    except Exception:
        pass


async def _enter(bot: Bot, m: Message, uid: int, lang: str):
    """Til tanlangan: obuna tekshiruvi -> bonus -> salomlashuv."""
    if miss := await _missing(bot, uid):
        return await send_card(bot, m.chat.id, t(lang, "gate"), _gate_kb(miss, lang))
    await _bonus(bot, uid)
    await send_card(bot, m.chat.id, t(lang, "welcome"), await _kb(lang))


# ---------------------------------------------------------------- buyruqlar
@router.message(CommandStart())
async def start(m: Message, command: CommandObject, bot: Bot):
    uid = m.from_user.id
    is_new = await db.upsert_user(uid, m.from_user.username, m.from_user.first_name)
    arg = command.args or ""
    if is_new and arg.startswith("ref_") and arg[4:].isdigit():
        await db.set_referrer(uid, int(arg[4:]))
    lang = await db.get_lang(uid)
    if not lang:                                    # birinchi marta: avval til tanlanadi
        return await send_card(bot, m.chat.id, t(None, "pick_lang"), _lang_kb())
    await _enter(bot, m, uid, lang)


@router.message(Command("lang"))
async def lang_cmd(m: Message, bot: Bot):
    await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    await send_card(bot, m.chat.id, t(None, "pick_lang"), _lang_kb())


@router.message(Command("help"))
async def help_(m: Message, bot: Bot):
    uid = m.from_user.id
    await db.upsert_user(uid, m.from_user.username, m.from_user.first_name)
    lang = await db.get_lang(uid)
    if not lang:
        return await send_card(bot, m.chat.id, t(None, "pick_lang"), _lang_kb())
    await _enter(bot, m, uid, lang)


@router.callback_query(F.data == "lang:menu")
async def lang_menu(cb: CallbackQuery, bot: Bot):
    await send_card(bot, cb.message.chat.id, t(None, "pick_lang"), _lang_kb())
    await cb.answer()


@router.callback_query(F.data.in_({"lang:uz", "lang:ru"}))
async def lang_chosen(cb: CallbackQuery, bot: Bot):
    uid, lang = cb.from_user.id, cb.data.split(":")[1]
    await db.upsert_user(uid, cb.from_user.username, cb.from_user.first_name)
    await db.set_lang(uid, lang)
    await _set_menu_button(bot, uid, lang)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer(t(lang, "lang_set"))
    await _enter(bot, cb.message, uid, lang)


@router.callback_query(F.data == "sub:check")
async def sub_check(cb: CallbackQuery, bot: Bot):
    uid = cb.from_user.id
    lang = await db.get_lang(uid) or i18n.DEFAULT
    if await _missing(bot, uid):
        return await cb.answer(t(lang, "not_all_subbed"), show_alert=True)
    await _bonus(bot, uid)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await send_card(bot, cb.message.chat.id, t(lang, "welcome"), await _kb(lang))
    await cb.answer()
