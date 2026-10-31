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
