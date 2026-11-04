"""Каждое сообщение пользователю — с баннером: фото + текст в подписи (caption).

Картинка: assets/banner.jpg (замените файл — бот сам перезальёт её при следующей отправке).
Первый раз файл загружается в Telegram, затем используется file_id (хранится в БД, быстро и без повторной загрузки).
Если картинки нет, подпись длиннее 1024 символов или фото не отправилось — уходит обычный текст.
"""
import hashlib
import logging
import os

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from db import database as db

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "banner.jpg")
CAPTION_MAX = 1024                      # лимит Telegram на подпись к фото
_sha: str | None = None
_fid: str | None = None
_loaded = False


def _digest() -> str:
    global _sha
    if _sha is None:
        try:
            with open(PATH, "rb") as f:
                _sha = hashlib.sha1(f.read()).hexdigest()[:12]
        except OSError:
            _sha = ""
    return _sha


async def _file_id() -> str | None:
    global _fid, _loaded
    if not _loaded:
        _loaded = True
        v = await db.get_setting("banner_file_id")
        if v and v.startswith(_digest() + ":"):         # id относится к ТЕКУЩЕЙ картинке
            _fid = v.split(":", 1)[1]
    return _fid


async def _remember(fid: str):
    global _fid
    _fid = fid
    await db.set_setting("banner_file_id", f"{_digest()}:{fid}")


async def send_card(bot: Bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """Отправить сообщение с баннером (или обычным текстом, если фото невозможно)."""
    global _fid
    if not _digest() or len(text) > CAPTION_MAX:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)
    if fid := await _file_id():
        try:
            return await bot.send_photo(chat_id, fid, caption=text, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            if "file" not in str(e).lower():            # не про file_id (например, чат не найден) — это не наша забота
                raise
            _fid = None                                 # file_id устарел — зальём картинку заново
    try:
        msg = await bot.send_photo(chat_id, FSInputFile(PATH), caption=text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if any(w in str(e).lower() for w in ("chat not found", "user not found", "blocked")):
            raise
        logging.warning("banner upload failed: %s", e)
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)
    if msg.photo:
        await _remember(msg.photo[-1].file_id)
    return msg
