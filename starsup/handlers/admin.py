"""Админ-панель. Доступ — только ID из ADMIN_IDS (.env)."""
import asyncio
import html
import re
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message, WebAppInfo

import config
from db import database as db
from services import fragment, fulfillment
import i18n
from services.notify import notify_t
from services.subscription import reset_cache

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

EDITABLE = {
    "card_uzcard": ("номер карты Uzcard", "card"), "card_humo": ("номер карты Humo", "card"),
    "card_holder": ("ФИО владельца карты", "text"), "support_username": ("юзернейм поддержки (@name)", "text"),
    "markup_stars": ("наценку на Stars, %", "num"), "markup_premium": ("наценку на Premium, %", "num"),
    "markup_gifts": ("наценку на NFT-подарки, %", "num"),
    "ref_signup_bonus": ("бонус за приглашённого друга, сум", "int"),
    "ref_percent": ("% от пополнений друзей", "num"),
    "ref_text": ("текст условий ({bonus} и {percent} подставятся сами)", "text"),
}
TOGGLES = {"enabled_stars": "⭐ Stars", "enabled_premium": "💎 Premium", "enabled_gifts": "🎁 NFT-подарки",
           "pay_uzcard": "💳 Оплата Uzcard", "pay_humo": "💳 Оплата Humo"}
ORDER_ST = {"processing": "⏳ в очереди", "delivering": "📤 выдаётся", "done": "✅ выдан", "refunded": "↩️ возврат", "review": "🔎 проверка"}
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
    [B(text="📣 Рассылка", callback_data="adm:bc"), B(text="📢 Каналы", callback_data="adm:channels")],
    [B(text="👥 Рефералы", callback_data="adm:ref"), B(text="➕ Начислить вручную", callback_data="adm:help")]])


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
                   "/products — товары и закупочные цены\n/setbase &lt;id&gt; &lt;цена&gt; — закупочная цена товара\n/gifts — подарки Telegram (gift_id)\n/setgift &lt;id товара&gt; &lt;gift_id&gt;\n/provider — состояние автовыдачи\n/fragment — TON-кошелёк и Fragment\n/review — заказы на проверке\n/done &lt;id&gt; · /refund &lt;id&gt; — решить зависший заказ",
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
    "ref": _edit_screen(["ref_signup_bonus", "ref_percent", "ref_text"], "👥 Рефералы (пустой текст = стандартный)"),
}


@router.callback_query(F.data.regexp(r"^adm:(cards|support|markup|ref)$"))
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
    elif kind == "int":
        if not val.isdigit():
            return await m.answer("Введите целое число, например 100")
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
    return "📦 <b>Последние заказы</b>\n\n" + ("\n".join(lines) or "Пока пусто"), KB(inline_keyboard=kb + [back()])


@router.callback_query(F.data == "adm:orders")
async def orders(cb: CallbackQuery):
    await show(cb, *await orders_view())
    await cb.answer()


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
        await notify_t(bot, t["user_id"], "topup_ok", amt=n(t["amount"]), bal=n(t["balance"]))
        if t.get("ref"):
            await notify_t(bot, t["ref"][0], "ref_topup", amt=n(t["ref"][1]))
    else:
        await notify_t(bot, t["user_id"], "topup_rejected", id=tid)
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
        await notify_t(bot, int(a[0]), "topup_ok", amt=n(a[1]), bal=n(bal))


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


# ======================= РАССЫЛКА =======================
class Broadcast(StatesGroup):
    msg = State()


_tasks: set = set()     # держим ссылки на фоновые задачи


async def broadcast_kb() -> KB:
    """Ровно 2 кнопки под каждым сообщением рассылки."""
    rows = [[B(text="🛍 Открыть Mini App", web_app=WebAppInfo(url=config.WEBAPP_URL))]]
    if url := await db.support_url():
        rows.append([B(text="💬 Поддержка", url=url)])
    return KB(inline_keyboard=rows)


@router.callback_query(F.data == "adm:bc")
async def bc_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Broadcast.msg)
    await cb.message.answer("📣 Отправьте сообщение для рассылки: текст, фото, видео или GIF (с подписью).\n"
                            "Кнопки «Открыть Mini App» и «Поддержка» добавятся автоматически.\nОтмена — /admin")
    await cb.answer()


@router.message(Broadcast.msg)
async def bc_preview(m: Message, state: FSMContext, bot: Bot):
    if m.text and m.text.startswith("/"):
        return await m.answer("Отправьте текст/фото/видео. Отмена — /admin")
    if m.content_type not in ("text", "photo", "video", "animation"):
        return await m.answer("Поддерживаются текст, фото, видео и GIF.")
    await state.update_data(chat_id=m.chat.id, msg_id=m.message_id)
    kb = await broadcast_kb()
    await bot.copy_message(m.chat.id, m.chat.id, m.message_id, reply_markup=kb)
    total = len(await db.all_user_ids())
    warn = "" if len(kb.inline_keyboard) == 2 else "\n⚠️ Юзернейм поддержки не задан — кнопки «Поддержка» не будет."
    await m.answer(f"👆 Так увидят пользователи. Получателей: <b>{total}</b>.{warn}",
                   reply_markup=KB(inline_keyboard=[[B(text="✅ Отправить всем", callback_data="bc:go"),
                                                     B(text="❌ Отмена", callback_data="adm:menu")]]))


@router.callback_query(F.data == "bc:go")
async def bc_go(cb: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    if not d.get("msg_id"):
        return await cb.answer("Сначала подготовьте сообщение", show_alert=True)
    await state.clear()
    t = asyncio.create_task(_run_broadcast(bot, cb.from_user.id, d["chat_id"], d["msg_id"]))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    await cb.message.edit_text("🚀 Рассылка запущена. Пришлю отчёт, когда закончится.")
    await cb.answer()


async def _run_broadcast(bot: Bot, admin_id: int, chat_id: int, msg_id: int):
    kb, ok, blocked, failed = await broadcast_kb(), 0, 0, 0
    ids = await db.all_user_ids()
    for uid in ids:
        try:
            await bot.copy_message(uid, chat_id, msg_id, reply_markup=kb)
            ok += 1
        except TelegramRetryAfter as ex:
            await asyncio.sleep(ex.retry_after + 1)
            try:
                await bot.copy_message(uid, chat_id, msg_id, reply_markup=kb)
                ok += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            blocked += 1
            await db.mark_blocked(uid)
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)          # ~20 сообщений/сек — в пределах лимитов Telegram
    await bot.send_message(admin_id, f"📣 <b>Рассылка завершена</b>\n✅ Доставлено: {ok}\n"
                                     f"🚫 Заблокировали бота: {blocked}\n⚠️ Ошибки: {failed}\nВсего: {len(ids)}")


# ======================= ОБЯЗАТЕЛЬНЫЕ КАНАЛЫ =======================
class AddChannel(StatesGroup):
    ref = State()


async def channels_view():
    chs = await db.list_channels()
    lines = [f"• {e(c['title'])} — {e('@' + c['username'] if c['username'] else c['chat_id'])}" for c in chs]
    text = ("📢 <b>Обязательные каналы</b>\n\n" + ("\n".join(lines) if lines else "Список пуст — проверка подписки выключена.")
            + "\n\nБот должен быть администратором канала/группы.")
    kb = [[B(text=f"❌ Удалить: {c['title'][:28]}", callback_data=f"ch:del:{c['id']}")] for c in chs]
    return text, KB(inline_keyboard=kb + [[B(text="➕ Добавить канал", callback_data="ch:add")], back()])


@router.callback_query(F.data == "adm:channels")
async def channels(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, *await channels_view())
    await cb.answer()


@router.callback_query(F.data == "ch:add")
async def ch_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddChannel.ref)
    await cb.message.answer("Отправьте @username канала или его ID (для приватных: -100…).\n"
                            "Сначала сделайте бота администратором канала. Отмена — /admin")
    await cb.answer()


@router.message(AddChannel.ref)
async def ch_save(m: Message, state: FSMContext, bot: Bot):
    raw = (m.text or "").strip()
    if not raw or raw.startswith("/"):
        return await m.answer("Отправьте @username или ID канала. Отмена — /admin")
    ref = int(raw) if re.fullmatch(r"-?\d+", raw) else "@" + re.sub(r"^(https?://)?(t\.me/)?@?", "", raw).split("/")[0]
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
    except Exception as ex:
        return await m.answer(f"⚠️ Не удалось найти канал: {e(ex)}\nДобавьте бота администратором и попробуйте снова.")
    if member.status not in ("administrator", "creator"):
        return await m.answer("⚠️ Бот не администратор этого канала. Сделайте его админом и повторите.")
    link = f"https://t.me/{chat.username}" if chat.username else chat.invite_link
    if not link:
        try:
            link = await bot.export_chat_invite_link(chat.id)
        except Exception:
            link = None
    await db.add_channel(chat.id, chat.username, chat.title or str(chat.id), link)
    reset_cache()
    await state.clear()
    await m.answer(f"✅ Добавлено: {e(chat.title)}", reply_markup=KB(inline_keyboard=[[B(text="📢 К каналам", callback_data="adm:channels")]]))


@router.callback_query(F.data.regexp(r"^ch:del:\d+$"))
async def ch_del(cb: CallbackQuery):
    await db.delete_channel(int(cb.data.split(":")[2]))
    reset_cache()
    await show(cb, *await channels_view())
    await cb.answer("Удалено")


# ======================= АВТОВЫДАЧА: служебные команды (только для нештатных ситуаций) =======================
@router.message(Command("provider"))
async def provider_status(m: Message):
    kind, data = await fulfillment.tg_call("getMyStarBalance")
    bal = data.get("amount") if kind == "ok" and isinstance(data, dict) else f"недоступно ({e(data)})"
    rows = await db.pool.fetch("SELECT status, count(*) c FROM orders GROUP BY status")
    st = ", ".join(f"{r['status']}: {r['c']}" for r in rows) or "—"
    prov = "настроен" if config.PROVIDER_URL and config.PROVIDER_TOKEN else "❌ не настроен"
    await m.answer(f"⚙️ <b>Автовыдача</b>\nStars на балансе бота: <b>{bal}</b>\nHTTP-провайдер (Stars): {prov}\n"
                   f"Premium: {config.PREMIUM_MODE}\nЗаказы: {st}")


@router.message(Command("fragment"))
async def fragment_status(m: Message):
    if not fragment.configured():
        return await m.answer("❌ Fragment не настроен: задайте FRAGMENT_HASH, FRAGMENT_COOKIES, TON_MNEMONIC в .env")
    try:
        w = await fragment.wallet_info()
    except Exception as ex:
        return await m.answer(f"⚠️ Кошелёк недоступен: {e(ex)}")
    await m.answer(f"💎 <b>Fragment / TON</b>\nКошелёк: <code>{w['address']}</code>\nБаланс: <b>{w['ton']:.3f} TON</b>\n"
                   f"Stars: {config.STARS_MODE} · Premium: {config.PREMIUM_MODE}\nЛимит на заказ: {config.FRAGMENT_MAX_TON} TON")


@router.message(Command("gifts"))
async def gifts(m: Message):
    kind, data = await fulfillment.tg_call("getAvailableGifts")
    if kind != "ok":
        return await m.answer(f"⚠️ {e(data)}")
    lines = [f"<code>{g['id']}</code> · {g.get('star_count')}⭐ {e((g.get('sticker') or {}).get('emoji'))}"
             for g in data.get("gifts", [])[:40]]
    await m.answer("🎁 <b>Подарки Telegram</b> (gift_id · цена)\n" + "\n".join(lines) +
                   "\n\nПривязать к товару: /setgift &lt;id товара&gt; &lt;gift_id&gt;")


@router.message(Command("setgift"))
async def setgift(m: Message, command: CommandObject):
    a = (command.args or "").split()
    if len(a) != 2 or not a[0].isdigit():
        return await m.answer("Использование: /setgift &lt;id товара&gt; &lt;gift_id&gt;  (id — из /products, gift_id — из /gifts)")
    r = await db.pool.execute("UPDATE products SET gift_id=$2 WHERE id=$1 AND category='gifts'", int(a[0]), a[1])
    await m.answer("✅ Привязано" if r.endswith("1") else "Товар не найден или это не подарок")


@router.message(Command("review"))
async def review(m: Message):
    rows = await db.pool.fetch("SELECT * FROM orders WHERE status IN ('review','delivering') ORDER BY id DESC LIMIT 20")
    await m.answer("🔎 <b>Заказы на проверке</b>\n" + ("\n".join(
        f"#{o['id']} · {e(o['title'])} · {n(o['price'])} сум · user <code>{o['user_id']}</code> · {o['status']}\n   {e(o['error'])}"
        for o in rows) or "Нет") + "\n\n/done &lt;id&gt; — выдано · /refund &lt;id&gt; — вернуть деньги")


async def _settle(m: Message, command: CommandObject, bot: Bot, action: str):
    arg = (command.args or "").strip()
    if not arg.isdigit():
        return await m.answer("Укажите номер заказа, например /refund 15")
    try:
        o = await db.order_action(int(arg), action, allowed=("review", "processing"))
    except db.BotError as ex:
        return await m.answer(f"⚠️ {ex.message}")
    if action == "done":
        lt = i18n.loc_title(o["title"], await db.get_lang(o["user_id"]))
        await notify_t(bot, o["user_id"], "order_done", id=arg, title=lt)
    else:
        await notify_t(bot, o["user_id"], "order_rejected", id=arg, amt=n(o["price"]))
    await m.answer("✅ Готово")


@router.message(Command("done"))
async def done_cmd(m: Message, command: CommandObject, bot: Bot):
    await _settle(m, command, bot, "done")


@router.message(Command("refund"))
async def refund_cmd(m: Message, command: CommandObject, bot: Bot):
    await _settle(m, command, bot, "refund")


@router.message(Command("payments"))
async def payments_diag(m: Message):
    """Диагностика приёма платежей: ожидающие пополнения и последние сообщения CardXabar, дошедшие до бота."""
    pend = await db.pool.fetch("SELECT id,user_id,amount,expires_at > now() AS alive, "
                               "to_char(expires_at AT TIME ZONE 'Asia/Tashkent','HH24:MI:SS') AS till "
                               "FROM topups WHERE status='pending' ORDER BY id DESC LIMIT 8")
    ev = await db.pool.fetch("SELECT amount, matched_topup, raw, to_char(created_at AT TIME ZONE 'Asia/Tashkent','DD.MM HH24:MI:SS') AS at "
                             "FROM bank_events ORDER BY created_at DESC LIMIT 8")
    lines = ["<b>⏳ Ожидают оплаты</b>"] + [
        f"#{r['id']} · user {r['user_id']} · <b>{n(r['amount'])}</b> сум · до {r['till']}" + ("" if r["alive"] else " (истёк)")
        for r in pend] if pend else ["<b>⏳ Ожидают оплаты</b>\nнет"]
    lines += ["", "<b>📥 Последние сообщения CardXabar, дошедшие до бота</b>"]
    if not ev:
        lines.append("пусто — до бота НИ ОДНО сообщение не дошло (проверьте listener, см. README)")
    for r in ev:
        st = f"зачислено #{r['matched_topup']}" if r["matched_topup"] else ("не распознано" if r["amount"] is None else "нет подходящего пополнения")
        first = (r["raw"] or "").replace("\n", " ")[:50]
        lines.append(f"{r['at']} · {n(r['amount']) if r['amount'] else '—'} · {st}\n<code>{e(first)}</code>")
    await m.answer("\n".join(lines))
