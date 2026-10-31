"""Админ-панель. Доступ — только ID из ADMIN_IDS (.env)."""
import html
import re
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message

import config
from db import database as db
from services.notify import notify_user

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

EDITABLE = {
    "card_uzcard": ("номер карты Uzcard", "card"), "card_humo": ("номер карты Humo", "card"),
    "card_holder": ("ФИО владельца карты", "text"), "support_username": ("юзернейм поддержки (@name)", "text"),
    "markup_stars": ("наценку на Stars, %", "num"), "markup_premium": ("наценку на Premium, %", "num"),
    "markup_gifts": ("наценку на NFT-подарки, %", "num"),
}
TOGGLES = {"enabled_stars": "⭐ Stars", "enabled_premium": "💎 Premium", "enabled_gifts": "🎁 NFT-подарки",
           "pay_uzcard": "💳 Оплата Uzcard", "pay_humo": "💳 Оплата Humo"}
ORDER_ST = {"processing": "⏳ в работе", "done": "✅ выдан", "refunded": "↩️ возврат"}
TOPUP_ST = {"pending": "⏳ ожидает", "paid": "✅ зачислено", "expired": "⌛ истёк", "rejected": "❌ отклонён"}


class Edit(StatesGroup):
    value = State()


def n(x) -> str:
    return f"{int(x):,}".replace(",", " ")


def e(x) -> str:
    return html.escape(str(x or "—"))


def back(to="adm:menu"):
    return [B(text="‹ Назад", callback_data=to)]


async def show(cb: CallbackQuery, text: str, kb: KB):
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass


MENU = KB(inline_keyboard=[
    [B(text="💳 Реквизиты", callback_data="adm:cards"), B(text="🛟 Поддержка", callback_data="adm:support")],
    [B(text="📈 Наценки", callback_data="adm:markup"), B(text="🔀 Тумблеры", callback_data="adm:toggles")],
    [B(text="📦 Заказы", callback_data="adm:orders"), B(text="💰 Пополнения", callback_data="adm:topups")],
    [B(text="➕ Начислить вручную", callback_data="adm:help")]])


@router.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🔧 <b>Админ-панель</b>", reply_markup=MENU)


@router.callback_query(F.data == "adm:menu")
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, "🔧 <b>Админ-панель</b>", MENU)
    await cb.answer()


@router.callback_query(F.data == "adm:help")
async def help_(cb: CallbackQuery):
    await show(cb, "<b>Команды</b>\n/credit &lt;tg_id&gt; &lt;сумма&gt; — начислить (отрицательная — списать)\n"
                   "/user &lt;tg_id&gt; — карточка пользователя, его платежи и заказы\n"
                   "/products — товары и закупочные цены\n/setbase &lt;id&gt; &lt;цена&gt; — закупочная цена товара",
               KB(inline_keyboard=[back()]))
    await cb.answer()


# ---------- реквизиты / поддержка / наценки ----------
def _edit_screen(keys, title):
    async def build():
        s = await db.get_settings()
        text = f"<b>{title}</b>\n\n" + "\n".join(f"• {EDITABLE[k][0]}: <code>{e(s[k])}</code>" for k in keys)
        rows = [[B(text=f"✏️ {EDITABLE[k][0]}", callback_data=f"set:{k}")] for k in keys]
        return text, KB(inline_keyboard=rows + [back()])
    return build


SCREENS = {
    "cards": _edit_screen(["card_uzcard", "card_humo", "card_holder"], "💳 Реквизиты карты"),
    "support": _edit_screen(["support_username"], "🛟 Поддержка"),
    "markup": _edit_screen(["markup_stars", "markup_premium", "markup_gifts"], "📈 Наценки (изменения сразу в магазине)"),
}


@router.callback_query(F.data.regexp(r"^adm:(cards|support|markup)$"))
async def edit_screen(cb: CallbackQuery):
    text, kb = await SCREENS[cb.data.split(":")[1]]()
    await show(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("set:"))
async def ask_value(cb: CallbackQuery, state: FSMContext):
    key = cb.data[4:]
    if key not in EDITABLE:
        return await cb.answer()
    await state.set_state(Edit.value)
    await state.update_data(key=key)
    await cb.message.answer(f"Введите {EDITABLE[key][0]}.\nОтмена — /admin")
    await cb.answer()


@router.message(Edit.value, F.text, ~F.text.startswith("/"))
async def save_value(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    kind, val = EDITABLE[key][1], m.text.strip()
    if kind == "card":
        digits = re.sub(r"\D", "", val)
        if len(digits) != 16:
            return await m.answer("Нужно 16 цифр номера карты. Попробуйте ещё раз.")
        val = " ".join(digits[i:i + 4] for i in range(0, 16, 4))
    elif kind == "num":
        try:
            d = Decimal(val.replace(",", "."))
        except InvalidOperation:
            return await m.answer("Введите число, например 7.5")
        if not 0 <= d <= 500:
            return await m.answer("Наценка должна быть от 0 до 500 %")
        val = str(d)
    elif key == "support_username":
        val = val.lstrip("@")
    await db.set_setting(key, val)
    await state.clear()
    await m.answer(f"✅ Сохранено: <code>{e(val)}</code>", reply_markup=KB(inline_keyboard=[back()]))


# ---------- тумблеры ----------
async def toggles_view():
    s = await db.get_settings()
    rows = [[B(text=f"{'✅' if s[k] == '1' else '⛔️'} {t}", callback_data=f"tg:{k}")] for k, t in TOGGLES.items()]
    return ("🔀 <b>Тумблеры</b>\nВыключенное недоступно для покупки: пользователь увидит "
            "«Сервис временно недоступен. Обратитесь в поддержку».", KB(inline_keyboard=rows + [back()]))


@router.callback_query(F.data == "adm:toggles")
async def toggles(cb: CallbackQuery):
    await show(cb, *await toggles_view())
    await cb.answer()


@router.callback_query(F.data.startswith("tg:"))
async def do_toggle(cb: CallbackQuery):
    key = cb.data[3:]
    if key in TOGGLES:
        await db.toggle(key)
    await show(cb, *await toggles_view())
    await cb.answer("Переключено")


# ---------- заказы ----------
async def orders_view():
    rows = await db.pool.fetch("SELECT * FROM orders ORDER BY id DESC LIMIT 10")
    lines, kb = [], []
    for o in rows:
        lines.append(f"#{o['id']} · {e(o['title'])} · {n(o['price'])} сум · user <code>{o['user_id']}</code> "
                     f"→ @{e(o['recipient'])} · {ORDER_ST.get(o['status'], o['status'])}")
        if o["status"] == "processing":
            kb.append([B(text=f"✅ #{o['id']} выдан", callback_data=f"ord:done:{o['id']}"),
                       B(text=f"❌ #{o['id']} вернуть", callback_data=f"ord:refund:{o['id']}")])
    return "📦 <b>Последние заказы</b>\n\n" + ("\n".join(lines) or "Пока пусто"), KB(inline_keyboard=kb + [back()])


@router.callback_query(F.data == "adm:orders")
async def orders(cb: CallbackQuery):
    await show(cb, *await orders_view())
    await cb.answer()


@router.callback_query(F.data.regexp(r"^ordn?:(done|refund):\d+$"))
async def order_act(cb: CallbackQuery, bot: Bot):
    pref, act, oid = cb.data.split(":")
    try:
        o = await db.order_action(int(oid), act)
    except db.BotError as ex:
        return await cb.answer(ex.message, show_alert=True)
    if act == "done":
        await notify_user(bot, o["user_id"], f"✅ Заказ #{oid} ({o['title']}) выполнен. Спасибо за покупку!")
    else:
        await notify_user(bot, o["user_id"], f"↩️ Заказ #{oid} отклонён, {n(o['price'])} сум возвращены на баланс.")
    await cb.answer("Готово")
    if pref == "ordn":
        await show(cb, cb.message.html_text + f"\n\n{'✅ Выдан' if act == 'done' else '↩️ Отклонён, деньги возвращены'}",
                   KB(inline_keyboard=[]))
    else:
        await show(cb, *await orders_view())


# ---------- пополнения ----------
def _topup_lines(rows):
    lines, kb = [], []
    for t in rows:
        lines.append(f"#{t['id']} · {n(t['amount'])} сум · {t['method']} · user <code>{t['user_id']}</code> · "
                     f"{TOPUP_ST.get(t['status'], t['status'])}")
        if t["status"] in ("pending", "expired"):
            kb.append([B(text=f"✅ #{t['id']} подтвердить", callback_data=f"tp:ok:{t['id']}"),
                       B(text=f"❌ #{t['id']}", callback_data=f"tp:no:{t['id']}")])
    return lines, kb


async def topups_view():
    rows = await db.pool.fetch("SELECT * FROM topups ORDER BY id DESC LIMIT 10")
    lines, kb = _topup_lines(rows)
    return "💰 <b>Последние пополнения</b>\n\n" + ("\n".join(lines) or "Пока пусто"), KB(inline_keyboard=kb + [back()])


@router.callback_query(F.data == "adm:topups")
async def topups(cb: CallbackQuery):
    await show(cb, *await topups_view())
    await cb.answer()


@router.callback_query(F.data.regexp(r"^tp:(ok|no):\d+$"))
async def topup_act(cb: CallbackQuery, bot: Bot):
    _, act, tid = cb.data.split(":")
    try:
        t = await db.resolve_topup(int(tid), act == "ok")
    except db.BotError as ex:
        return await cb.answer(ex.message, show_alert=True)
    if act == "ok":
        await notify_user(bot, t["user_id"], f"✅ Баланс пополнен на {n(t['amount'])} сум. Баланс: {n(t['balance'])} сум")
    else:
        await notify_user(bot, t["user_id"], f"❌ Пополнение #{tid} отклонено. Обратитесь в поддержку.")
    await cb.answer("Готово")
    await show(cb, *await topups_view())


# ---------- команды ----------
@router.message(Command("user"))
async def user_card(m: Message, command: CommandObject):
    if not (command.args or "").strip().isdigit():
        return await m.answer("Использование: /user &lt;tg_id&gt;")
    uid = int(command.args)
    u = await db.pool.fetchrow("SELECT * FROM users WHERE tg_id=$1", uid)
    if not u:
        return await m.answer("Пользователь не найден")
    tps = await db.pool.fetch("SELECT * FROM topups WHERE user_id=$1 ORDER BY id DESC LIMIT 5", uid)
    ords = await db.pool.fetch("SELECT * FROM orders WHERE user_id=$1 ORDER BY id DESC LIMIT 5", uid)
    lines, kb = _topup_lines(tps)
    text = (f"👤 <code>{uid}</code> @{e(u['username'])}\nБаланс: <b>{n(u['balance'])}</b> сум\n\n"
            f"<b>Пополнения</b>\n{chr(10).join(lines) or '—'}\n\n<b>Заказы</b>\n" +
            ("\n".join(f"#{o['id']} {e(o['title'])} · {n(o['price'])} · {ORDER_ST.get(o['status'])}" for o in ords) or "—"))
    await m.answer(text, reply_markup=KB(inline_keyboard=kb) if kb else None)


@router.message(Command("credit"))
async def credit(m: Message, command: CommandObject, bot: Bot):
    a = (command.args or "").split()
    if len(a) < 2 or not a[0].isdigit() or not re.fullmatch(r"-?\d+", a[1]):
        return await m.answer("Использование: /credit &lt;tg_id&gt; &lt;сумма&gt;")
    try:
        bal = await db.manual_credit(int(a[0]), int(a[1]), f"admin:{m.from_user.id}")
    except db.BotError as ex:
        return await m.answer(f"⚠️ {ex.message}")
    await m.answer(f"✅ Готово. Новый баланс {a[0]}: {n(bal)} сум")
    if int(a[1]) > 0:
        await notify_user(bot, int(a[0]), f"✅ Баланс пополнен на {n(a[1])} сум. Баланс: {n(bal)} сум")


@router.message(Command("products"))
async def products(m: Message):
    rows = await db.pool.fetch("SELECT * FROM products ORDER BY category, sort")
    await m.answer("<b>Товары (закупка, сум)</b>\n" + "\n".join(
        f"{r['id']}. {e(r['title'])} — {n(r['base_price'])}" for r in rows))


@router.message(Command("setbase"))
async def setbase(m: Message, command: CommandObject):
    a = (command.args or "").split()
    if len(a) != 2 or not all(x.isdigit() for x in a):
        return await m.answer("Использование: /setbase &lt;id товара&gt; &lt;цена в сумах&gt;")
    r = await db.pool.execute("UPDATE products SET base_price=$2 WHERE id=$1", int(a[0]), int(a[1]))
    await m.answer("✅ Обновлено" if r.endswith("1") else "Товар не найден")
