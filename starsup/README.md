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

## Смена дизайна
Весь вид Mini App — в папке `webapp/design/` (`index.html`, `style.css`, картинки). Замените файлы там и задеплойте. См. `webapp/design/README.md`.

## Автовыдача
Покупка → списание баланса (`FOR UPDATE`, COMMIT) → `fulfillment.schedule()` выдаёт товар в фоне, без кнопок админа.
- **Premium** и **NFT-подарки** — нативно через Bot API (`giftPremiumSubscription`, `sendGift`), оплата Stars с баланса бота.
  Для подарков привяжите gift_id: `/gifts` → `/setgift <id товара> <gift_id>`.
- **Stars** — через HTTP-провайдера: `PROVIDER_URL`, `PROVIDER_TOKEN` (см. `.env.example`); формат запроса — `services/fulfillment.py::_http`.
- Не выдано точно → авто-возврат. Неясный результат (таймаут/5xx/рестарт) → заказ `review`, деньги удержаны, админу алерт; решение: `/done <id>` или `/refund <id>`.
- Состояние: `/provider`, `/review`.

## Важно
- Цена = закупка × (1 + наценка%), округление вверх до 100 сум. Закупочные цены в `db/database.py::SEED` — примерные,
  поменяйте командой `/setbase`.
- Баланс защищён: `SELECT ... FOR UPDATE` + `CHECK (balance >= 0)` + идемпотентные операции.


## Fragment через TON (Stars / Premium) — `services/fragment.py`
Неофициальный путь: у Fragment нет API, модуль повторяет запросы сайта от вашей сессии и платит TON с кошелька.
1. Заведите **отдельный** TON-кошелёк (V4R2), положите немного TON; 24 слова — в `TON_MNEMONIC` (только в `.env` на сервере).
2. Войдите на fragment.com этим кошельком (TonConnect). В браузере (F12): `FRAGMENT_COOKIES` — cookies `stel_ssid`,
   `stel_token`, `stel_dt`, `stel_ton_token` строкой `a=b; c=d`; `FRAGMENT_HASH` — из исходника страницы fragment.com/stars/buy,
   поле `"apiUrl":"\/api?hash=…"`.
3. `STARS_MODE=fragment` (и `PREMIUM_MODE=fragment`, если Premium тоже через Fragment). Проверка: `/fragment` в боте.
4. Cookies со временем протухают — при ошибке сессии заказы возвращаются клиентам, а админ получает причину.
Защита: лимит `FRAGMENT_MAX_TON` на заказ, алерт при балансе ниже `FRAGMENT_LOW_TON`, TON-платежи строго по одному.
Парсер проверки прихода: `python tests/check_parser.py` (добавьте свои реальные сообщения в SAMPLES).

## Если пополнение не зачисляется
1. Отправьте боту `/payments` (админ): видно ожидающие платежи и последние сообщения CardXabar, дошедшие до бота.
   - «пусто» → сообщения не доходят: проверьте listener (п. 2) и `WEBHOOK_SECRET`.
   - «не распознано» → пришлите текст сообщения, поправим парсер.
   - «нет подходящего пополнения» → сумма/время не совпали (платёж позже TTL или другая сумма).
2. Listener: `docker compose --profile listener ps` и `docker compose --profile listener logs listener --tail 50`.
   Должна быть строка `Listening @CardXabarBot…`, а при каждом платеже — `200 {"ok": true, "status": "matched"}`.
   Listener должен быть залогинен в тот аккаунт Telegram, куда CardXabarBot присылает уведомления об этой карте.

## Render + GitHub + Neon (Docker/Caddy kerak emas)
- GitHub — kod saqlanadi. Neon — baza (`DATABASE_URL`). Render — bot ishlaydigan server.
- Render: New → Web Service → GitHub repo. Runtime: Python 3. Build: `pip install -r requirements.txt`. Start: `python main.py`.
- Instance turi: **Starter** (bepul tarif 15 daqiqa jim tursa uxlab qoladi — bot va listener to'xtaydi).
- Environment: `BOT_TOKEN`, `DATABASE_URL`, `WEBAPP_URL` (= Render manzili, https://...onrender.com), `WEBHOOK_SECRET`, `ADMIN_IDS`,
  `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`. (`DOMAIN` va `WEBHOOK_URL` kerak emas.)
- `TG_SESSION`: o'z kompyuteringizda `pip install telethon` va `python parser/make_session.py`. Bu satr = Telegram akkauntingizga to'liq kirish, sir saqlang.
- Ishga tushgach bot adminlarga "✅ CardXabar listener запущен" xabarini yuboradi. `/payments` — diagnostika.
