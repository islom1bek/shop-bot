# Telegram shop bot (single-file edition)

Python 3.12 · aiogram 3 · PostgreSQL · SQLAlchemy 2 (async) · Docker Compose.
The whole bot lives in `bot.py`. The database schema is created automatically on start (idempotent).
All messages shown to customers/admins are in Russian.

## Status: read this first
`bot.py` was statically checked (compiles, pyflakes clean) and smoke-tested: configuration errors, PostgreSQL
connection, schema creation (run twice), dispatcher assembly. **The full customer/admin flows were NOT run against the real
Telegram API and no automated test suite is included for this single-file version.** Test every flow with a test bot
before real use (checklist at the bottom). Deployment files (Compose, backup scripts) are untested on a real VPS.

## 1. Create the bot and find IDs
1. In Telegram open **@BotFather** → `/newbot` → copy the token.
2. Your numeric ID: message **@userinfobot** (or any bot that shows your ID). Use the number, never a @username.

## 2. Configure
```bash
cp .env.example .env
nano .env        # BOT_TOKEN, OWNER_TELEGRAM_ID, POSTGRES_PASSWORD at minimum
chmod 600 .env
```

## 3. Run locally (without Docker)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# PostgreSQL must be running; set POSTGRES_HOST=localhost in .env
python bot.py
```

## 4. Deploy on a Linux VPS (Docker)
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker
# upload the project folder to the server, then:
cd telegram_shop_bot
cp .env.example .env && nano .env && chmod 600 .env
docker compose up -d --build
docker compose logs -f bot        # look for "bot authorised as @..."
```
Restarts: containers use `restart: unless-stopped`, so the bot returns after a reboot. Stop gracefully with `docker compose stop`.
Availability still depends on your VPS, network, Telegram and maintenance — no uptime is promised.

## 5. First use
Open your bot, send `/start` as the owner → **Настройки договора** → upload the offer PDF → **Города** → **Товары** →
**Способы оплаты** (set the USDT TRC20 address). Customers see nothing until an offer exists. See `OWNER_GUIDE_RU.md`.

## 6. Update / roll back
```bash
git pull   # or upload the new bot.py
docker compose up -d --build
docker compose logs --tail=50 bot
# rollback: restore the previous bot.py and run `docker compose up -d --build` again
```
Schema changes are applied additively on start. Always take a backup before updating.

## 7. Backups
```bash
./scripts/backup.sh                         # creates backups/shopbot_*.dump (chmod 600), prunes old ones
./scripts/verify_backup.sh backups/<file>   # proves it restores (into a temporary DB)
./scripts/restore.sh backups/<file>         # replaces current data
```
Cron (daily 03:00): `0 3 * * * cd /home/USER/telegram_shop_bot && ./scripts/backup.sh >> logs/backup.log 2>&1`
Copy dumps off the server regularly; they contain customer data — never put them in a public folder.

## 8. Design notes
- **Payment deadline:** stored in PostgreSQL (`orders.payment_deadline_at`), swept every 15 s with `FOR UPDATE SKIP LOCKED`;
  receipt acceptance and timeout cancellation lock the same row, so only one can win. Survives restarts.
- **After an admin rejects a receipt** the customer gets a new 10-minute window; after expiry the order is cancelled for good.
- **One unpaid order per customer** at a time (unique index) — this also makes receipts unambiguous.
- **Notifications** go through a durable `outbox` table with retry/backoff; an order becomes `DISPATCHED` only after the pickup
  notification was really delivered.
- **Receipts:** photo, PDF, or JPEG/PNG/WebP sent as a file are accepted; video, audio, voice, stickers, GIFs are rejected.
- **Variants** store attributes as JSON (any attribute names) instead of a separate attributes table.
- **Audit log** and **order snapshots** are protected by database triggers; max 3 active admins is enforced by a trigger too.
- **Staff** (owner/admins) skip the agreement gate; customers are silently ignored until they accept the current offer.

## 9. Known limitations
- FSM (multi-step input) state is kept in memory: a restart cancels half-finished admin forms (orders/payments are unaffected).
- Order filters in the owner panel are single-filter (one at a time).
- Broadcasts resume after restart; refunds after confirmed payment are not implemented.
- No rate limiting beyond ~12 events / 5 s per user; no web dashboard.
- Payment verification is manual; screenshots are not proof of payment.

## 10. Manual test checklist (use a test bot)
1. Owner: upload offer PDF, add a city, a product (photo, city, variant), set wallet. 2. Customer: `/start` (must get PDF),
send random text before accepting (must get no reply), accept, order, double-tap "Подтвердить" (one order only).
3. Card button → "технические работы". 4. Send video/voice/sticker as receipt → rejected; send photo/PDF → accepted.
5. Wait 10 min on another order → auto-cancel, receipt afterwards refused. 6. Two admins press "Взять заказ" → one wins.
7. Approve/reject with reason, reject before payment. 8. Dispatch with photo/date/time → customer message, status DISPATCHED.
9. Support: claim, reply, close, reopen. 10. Admin tries owner buttons (must be refused). 11. Restart the bot during a pending order.
