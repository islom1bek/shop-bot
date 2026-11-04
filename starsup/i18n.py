"""Тили / Tillar: o'zbekcha va русский. Foydalanuvchiga ketadigan barcha bot xabarlari shu yerda.

Yangi matn qo'shish: ikkala tilga bir xil kalit bilan qo'shing. Til yo'q bo'lsa — o'zbekcha (default).
Mini App matnlari alohida: webapp/app.js ichidagi TR lug'ati.
"""
import re

LANGS = ("uz", "ru")
DEFAULT = "uz"

TEXTS = {
    "uz": {
        "pick_lang": "🌐 Tilni tanlang\n🌐 Выберите язык",
        "lang_set": "✅ Til o'rnatildi: O'zbekcha 🇺🇿",
        "menu_btn": "Do'kon",
        "welcome": ("👋 Bu yerda <b>Telegram Stars</b>, <b>Premium</b> va <b>NFT-sovg'alar</b> xarid qilishingiz mumkin. "
                    "To'lov — Uzcard va Humo kartalari orqali.\n\nDo'konni quyidagi tugma bilan oching."),
        "gate": "🔒 Do'kondan foydalanish uchun quyidagi kanallarga obuna bo'ling va «Obuna bo'ldim» tugmasini bosing.",
        "btn_open": "🛍 Do'konni ochish",
        "btn_support": "🛟 Yordam",
        "btn_subbed": "✅ Obuna bo'ldim",
        "btn_lang": "🌐 Til / Язык",
        "not_all_subbed": "Siz barcha kanallarga obuna bo'lmagansiz",
        "ref_joined": "🎉 Do'stingiz sizning havolangiz orqali qo'shildi — sizga +{amt} so'm",
        "ref_topup": "🎉 Do'stingiz hisobini to'ldirdi — sizga +{amt} so'm",
        "topup_ok": "✅ Balans {amt} so'mga to'ldirildi.\nJoriy balans: {bal} so'm",
        "topup_rejected": "❌ #{id} to'ldirish rad etildi. Yordamga murojaat qiling.",
        "order_done": "✅ Buyurtma #{id} bajarildi: {title}. Xaridingiz uchun rahmat!",
        "order_refund": ("↩️ #{id} buyurtmani ({title}) bajarib bo'lmadi. {amt} so'm balansga qaytarildi. "
                         "Keyinroq urinib ko'ring yoki yordamga yozing."),
        "order_review": ("⏳ Buyurtma #{id} ({title}) odatdagidan uzoqroq bajarilmoqda. Tekshiryapmiz — "
                         "pul yo'qolmaydi, natijani xabar qilamiz."),
        "order_rejected": "↩️ Buyurtma #{id} rad etildi, {amt} so'm balansga qaytarildi.",
        "thanks_gift": "Xaridingiz uchun rahmat! 🎁",
        "thanks_premium": "Xaridingiz uchun rahmat! 💎",
        "ref_default": ("Sizning havolangizdan yangi do'stingiz tashrif buyursa {bonus} so'm bonus olasiz va "
                        "do'stlaringizning har bir hisob to'ldirishidan {percent}% ulush olasiz"),
        "ref_share": "Stars, Premium va NFT sovg'alar — eng qulay narxlarda! 🚀",
    },
    "ru": {
        "pick_lang": "🌐 Tilni tanlang\n🌐 Выберите язык",
        "lang_set": "✅ Язык установлен: Русский 🇷🇺",
        "menu_btn": "Магазин",
        "welcome": ("👋 Здесь можно купить <b>Telegram Stars</b>, <b>Premium</b> и <b>NFT-подарки</b>. "
                    "Оплата — картами Uzcard и Humo.\n\nОткройте магазин кнопкой ниже."),
        "gate": "🔒 Чтобы пользоваться магазином, подпишитесь на каналы ниже и нажмите «Я подписался».",
        "btn_open": "🛍 Открыть магазин",
        "btn_support": "🛟 Поддержка",
        "btn_subbed": "✅ Я подписался",
        "btn_lang": "🌐 Til / Язык",
        "not_all_subbed": "Вы подписаны не на все каналы",
        "ref_joined": "🎉 Ваш друг присоединился по вашей ссылке — вам +{amt} сум",
        "ref_topup": "🎉 Ваш друг пополнил баланс — вам +{amt} сум",
        "topup_ok": "✅ Баланс пополнен на {amt} сум.\nТекущий баланс: {bal} сум",
        "topup_rejected": "❌ Пополнение #{id} отклонено. Обратитесь в поддержку.",
        "order_done": "✅ Заказ #{id} выдан: {title}. Спасибо за покупку!",
        "order_refund": ("↩️ Не удалось выдать заказ #{id} ({title}). {amt} сум возвращены на баланс. "
                         "Попробуйте позже или напишите в поддержку."),
        "order_review": ("⏳ Заказ #{id} ({title}) выдаётся дольше обычного. Мы проверяем — "
                         "деньги не пропадут, сообщим о результате."),
        "order_rejected": "↩️ Заказ #{id} отклонён, {amt} сум возвращены на баланс.",
        "thanks_gift": "Спасибо за покупку! 🎁",
        "thanks_premium": "Спасибо за покупку! 💎",
        "ref_default": ("Если по вашей ссылке придёт новый друг, вы получите {bonus} сум бонуса и {percent}% "
                        "от каждого пополнения баланса ваших друзей"),
        "ref_share": "Stars, Premium и NFT-подарки — по лучшим ценам! 🚀",
    },
}

_GIFT_UZ = {"Мишка": "Ayiqcha", "Сердце": "Yurak", "Роза": "Atirgul", "Торт": "Tort"}


def norm(lang: str | None) -> str:
    return lang if lang in LANGS else DEFAULT


def t(lang: str | None, key: str, **kw) -> str:
    s = TEXTS[norm(lang)].get(key) or TEXTS[DEFAULT][key]
    return s.format(**kw) if kw else s


def num(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def loc_title(title: str, lang: str | None) -> str:
    """Katalogdagi nomlar bazada ruscha saqlanadi — o'zbekcha ko'rsatish uchun tarjima qilamiz."""
    if norm(lang) != "uz":
        return title
    if m := re.fullmatch(r"Premium · (\d+) мес\S*", title):
        return f"Premium · {m[1]} oy"
    if m := re.fullmatch(r"NFT-подарок «(.+)»", title):
        return f"NFT-sovg'a «{_GIFT_UZ.get(m[1], m[1])}»"
    return title
