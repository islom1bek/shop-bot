# Дизайн Mini App

Всё, что отвечает за внешний вид, лежит в этой папке. Чтобы сменить дизайн — замените файлы здесь
(`index.html`, `style.css`, при необходимости картинки/шрифты) и сделайте деплой. Бэкенд и `webapp/app.js` менять не нужно.

## Файлы
- `logo.webp` — logotip (splash va shapka). Almashtirish: shu nomli fayl qo'ying.
- Matnlar: `data-i18n="kalit"` — tarjimalar `webapp/app.js` ichidagi `TR` da.
- `index.html` — каркас страницы, шапка, нижняя навигация, подключение шрифтов.
- `style.css` — все стили. Переменная `--bg` задаёт цвет шапки Telegram.
- Картинки/иконки/шрифты (`.svg .png .jpg .webp .gif .woff .woff2 .ico`) кладите сюда же и подключайте как `/static/имя_файла`.

## Контракт с `app.js` (не переименовывать)
**id в index.html:** `view`, `tabs`, `sheet`, `backdrop`, `toast`, `hi`, `ava` (<img> logotip), `balChip`, `splash`, `spFly` (animatsiya: logo `spFly` dan `ava` ga uchib boradi)
**data-атрибуты кнопок:** `data-act="goto|support|close"`, `data-tab="shop|topup|profile"` (3 кнопки в `#tabs`, активная получает класс `on`).
**Классы, которые создаёт app.js (их нужно стилизовать):**
`seg` (+ `on` на кнопке, переменные `--i` и `--n`), `grid`, `card` (`em`, `t`, `p`, `off`), `btn` (`ghost`), `field`, `quick`,
`pay`, `copy` (`sum`), `steps`, `timer`, `pulse`, `hero` (`big`), `list`, `row` (`l`, `r`), `st` (`ok`, `bad`, `wait`),
`empty`, `hint`, `big-em`, `kv`; на `body` при открытом окне ставится класс `sheet-open`.

## Магазин (список пакетов)
`renderShop()` в `app.js` рисует: переключатель категорий → заголовок → «Kimga?» (@username, кнопка «O'zimga») → список пакетов (radio) →
«O'zim kiritaman» (своё количество Stars, 50–100 000) → нижняя кнопка. Стили — блок «Магазин: получатель + список пакетов» в `style.css`.
Получатель: Stars — любой @username; Premium — только если `PREMIUM_MODE` не `telegram`; подарки — всегда сам покупатель.
Цена своего количества = цена 1 звезды ближайшего НИЖНЕГО пакета × количество (округление вверх до 100 сум) — `db._tier_unit`.

## Premium / подарки / профиль
- Premium: список сроков (`premHTML`) — цена за месяц и скидка относительно самого короткого срока считаются на клиенте.
- Подарки: сетка 3 в ряд (`giftsHTML`) + получатель + комментарий (до 128 симв., уходит как `text` в sendGift).
  Получатель подарка / Premium через Bot API — только тот, кто запускал бота (иначе ошибка `recipient_unknown`).
- Профиль: аватар из Telegram (`photo_url`), баланс, статистика (`db.user_stats`), язык и поддержка, история заказов/пополнений.
