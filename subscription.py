"""Проверка обязательной подписки на каналы."""
import logging
import time

from db import database as db

_ok: dict[int, float] = {}      # user_id -> когда последний раз подтвердили подписку
TTL = 120                       # секунд; кешируем только положительный результат


def reset_cache():
    _ok.clear()


async def missing_channels(bot, user_id: int) -> list[dict]:
    """Каналы, на которые пользователь НЕ подписан. Если бот не видит канал — не блокируем."""
    if time.time() - _ok.get(user_id, 0) < TTL:
        return []
    missing = []
    for ch in await db.list_channels():
        try:
            m = await bot.get_chat_member(ch["chat_id"], user_id)
            if m.status in ("left", "kicked") or (m.status == "restricted" and not getattr(m, "is_member", True)):
                missing.append(ch)
        except Exception as e:
            logging.warning("sub-check %s: %s", ch["chat_id"], e)
    if not missing:
        _ok[user_id] = time.time()
    return missing
