# @StarsUpPayBot — магазин Stars / Premium / NFT-подарков

Python 3.12 · Aiogram 3 · aiohttp · PostgreSQL (Neon) · Mini App (HTML/CSS/JS) · Docker

## Быстрый старт
1. `cp .env.example .env` и заполните: `BOT_TOKEN`, `DATABASE_URL` (Neon, `?sslmode=require`), `WEBAPP_URL`, `DOMAIN`, `ADMIN_IDS`, `WEBHOOK_SECRET`.
2. DNS домена → ваш сервер. `docker compose up -d --build` (Caddy сам выпустит HTTPS; Mini App требует HTTPS).
3. В @BotFather: имя бота `StarsUpPayBot`. Кнопка меню «Магазин» ставится ботом автоматически.
4. Напишите боту `/admin`: задайте номера Uzcard/Humo, ФИО, юзернейм поддержки, наценки.
   Таблицы создаются при первом запуске.

## Приём платежей из @CardXabarBot
`parser/cardxabar_listener.py` (Telethon) читает сообщения @CardXabarBot в вашем аккаунте и шлёт их в
`POST /webhook/cardxabar` (заголовок `X-Webhook-Secret`, тело `{"id": "...", "text": "..."}`).
Заполните `TG_API_ID`/`TG_API_HASH` (my.telegram.org), затем первый вход интерактивно:
`docker compose --profile listener run --rm listener`, после — `docker compose --profile listener up -d`.

Как сопоставляется платёж: при создании пополнения сумме добавляется 0–99 сум, чтобы среди ожидающих
платежей она была уникальной (UNIQUE-индекс). Пользователь переводит ровно эту сумму → поступление с такой
суммой автоматически зачисляется ему. Дубликаты уведомлений отсекаются (`bank_events`).
Не опознанные поступления приходят админам: `/credit <tg_id> <сумма>`.

**Проверьте парсер** `services/payments.py::parse_amount` на реальных уведомлениях вашего банка — формат текста
может отличаться (ключевые слова «Пополнение/Kirim/➕», строки «Баланс» игнорируются).

## Админ-панель (`/admin`, только `ADMIN_IDS`)
Реквизиты · поддержка · наценки (%) · тумблеры товаров и оплат · заказы (выдан / отклонить с возвратом) ·
пополнения (подтвердить/отклонить) · `/user <id>` · `/credit <id> <сумма>` · `/products` · `/setbase <id> <цена>`.

## Важно
- Цена = закупка × (1 + наценка%), округление вверх до 100 сум. Закупочные цены в `db/database.py::SEED` — примерные,
  поменяйте командой `/setbase`.
- Выдача товара **ручная**: заказ приходит админам с кнопками «Выдан / Отклонить и вернуть». Автовыдачу
  (Fragment/поставщик) подключайте после `db.purchase` в `webapp/api.py::buy`.
- Баланс защищён: `SELECT ... FOR UPDATE` + `CHECK (balance >= 0)` + идемпотентные операции.
