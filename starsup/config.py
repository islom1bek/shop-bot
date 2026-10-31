import os
from dotenv import load_dotenv

load_dotenv()


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"Не задана переменная {key} в .env")
    return v


BOT_TOKEN = _req("BOT_TOKEN")
DATABASE_URL = _req("DATABASE_URL")
WEBAPP_URL = _req("WEBAPP_URL").rstrip("/")
WEBHOOK_SECRET = _req("WEBHOOK_SECRET")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
PORT = int(os.getenv("PORT", "8080"))

# --- Автовыдача ---
# Premium и NFT-подарки по умолчанию выдаются нативно через Bot API (Stars с баланса бота).
PREMIUM_MODE = os.getenv("PREMIUM_MODE", "telegram")            # telegram | provider
# HTTP-провайдер (Fragment-шлюз) — для Stars (и Premium при PREMIUM_MODE=provider)
PROVIDER_URL = os.getenv("PROVIDER_URL", "").rstrip("/")
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "")
PROVIDER_STARS_PATH = os.getenv("PROVIDER_STARS_PATH", "/stars/buy")
PROVIDER_PREMIUM_PATH = os.getenv("PROVIDER_PREMIUM_PATH", "/premium/buy")
PROVIDER_STATUS_PATH = os.getenv("PROVIDER_STATUS_PATH", "/status/{id}")
PROVIDER_POLL_SECONDS = int(os.getenv("PROVIDER_POLL_SECONDS", "300"))
