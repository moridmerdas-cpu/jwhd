import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_int(key, default=0):
    try: return int(os.getenv(key, default))
    except (ValueError, TypeError): return default


def _get_admins(key):
    raw = os.getenv(key, "")
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


class Config:
    API_ID       = _get_int("API_ID")
    API_HASH     = os.getenv("API_HASH", "")
    BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
    BOT_NAME     = os.getenv("BOT_NAME", "Master Bot")
    ADMIN_IDS    = _get_admins("ADMIN_IDS")
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
    BASE_DIR     = BASE_DIR
    SESSION_DIR  = BASE_DIR / os.getenv("SESSION_DIR", "sessions")
    PROXY_DIR    = BASE_DIR / "proxies"
    LOG_DIR      = BASE_DIR / "logs"

    # ── Supabase (جایگزین SQLite) ──────────────────────────────
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")   # service_role key

    PROXY_START_PORT   = _get_int("PROXY_START_PORT", 40000)
    LOG_CHANNEL_ID     = _get_int("LOG_CHANNEL_ID", 0)
    LOG_LEVEL          = os.getenv("LOG_LEVEL", "INFO").upper()
    SHIFT_SIZE         = 75
    SHIFT_MINUTES      = 30

    # ── تارگت ─────────────────────────────────────────────────
    TARGET_GROUP_ID    = _get_int("TARGET_GROUP_ID", 0)

    AUTO_VIEW_ENABLED  = _get_int("AUTO_VIEW_ENABLED", 1) == 1
    AUTO_VIEW_DELAY_MS = _get_int("AUTO_VIEW_DELAY_MS", 0)

    # ── بازه تایم شیفت (ثانیه) ────────────────────────────────
    SHIFT_MIN_SEC: int = _get_int("SHIFT_MIN_SEC", 1500)   # 25 دقیقه
    SHIFT_MAX_SEC: int = _get_int("SHIFT_MAX_SEC", 2700)   # 45 دقیقه

    # ── Webhook ────────────────────────────────────────────────
    WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")
    WEBHOOK_PATH     = os.getenv("WEBHOOK_PATH", "/webhook")
    WEBHOOK_SECRET   = os.getenv("WEBHOOK_SECRET", "")
    WEBHOOK_HOST     = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    WEBHOOK_PORT     = _get_int("WEBHOOK_PORT", 8443)

    @classmethod
    def validate(cls):
        e = []
        if not cls.API_ID: e.append("API_ID")
        if not cls.API_HASH or len(cls.API_HASH) != 32: e.append("API_HASH")
        if not cls.BOT_TOKEN or ":" not in cls.BOT_TOKEN: e.append("BOT_TOKEN")
        if not cls.ADMIN_IDS: e.append("ADMIN_IDS")
        if len(cls.ENCRYPTION_KEY) != 32: e.append("ENCRYPTION_KEY")
        if not cls.SUPABASE_URL or not cls.SUPABASE_URL.startswith("https://"): e.append("SUPABASE_URL")
        if not cls.SUPABASE_KEY: e.append("SUPABASE_KEY")
        return e


for f in [Config.SESSION_DIR, Config.PROXY_DIR, Config.LOG_DIR, Config.PROXY_DIR / "warp_pool"]:
    f.mkdir(parents=True, exist_ok=True)
