"""
models/database.py  —  نسخه Supabase
جایگزین SQLite با supabase-py v2
همه function signature ها با نسخه قبلی سازگار هستن.
"""
import base64, hashlib, sys
from pathlib import Path
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from supabase import create_client, Client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config

# ── Supabase client (singleton) ───────────────────────────────
_supabase: Client | None = None

def _get_client() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return _supabase


# ── رمزنگاری session ──────────────────────────────────────────
def _get_fernet() -> Fernet:
    kb = hashlib.sha256(Config.ENCRYPTION_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(kb))

FERNET = _get_fernet()

def encrypt(t: str) -> str:
    return FERNET.encrypt(t.encode()).decode()

def decrypt(t: str) -> str:
    return FERNET.decrypt(t.encode()).decode()


# ── init_db ───────────────────────────────────────────────────
def init_db():
    """
    در Supabase جداول از قبل با supabase_schema.sql ساخته شدن.
    این تابع فقط مقادیر پیش‌فرض settings رو چک می‌کنه.
    """
    sb = _get_client()
    defaults = {
        "target_group_id":   str(Config.TARGET_GROUP_ID),
        "shift_min_sec":     str(Config.SHIFT_MIN_SEC),
        "shift_max_sec":     str(Config.SHIFT_MAX_SEC),
        "active_shift":      "1",
        "auto_view_enabled": "1",
    }
    for key, value in defaults.items():
        # upsert با on_conflict=ignore
        sb.table("settings").upsert(
            {"key": key, "value": value},
            ignore_duplicates=True
        ).execute()
    print("✅ Supabase آماده شد")


# ── Settings helpers ──────────────────────────────────────────
def get_setting(key: str, default=None):
    sb = _get_client()
    res = sb.table("settings").select("value").eq("key", key).limit(1).execute()
    if res and res.data:
        return res.data[0]["value"]
    return default


def set_setting(key: str, value):
    sb = _get_client()
    sb.table("settings").upsert({"key": key, "value": str(value)}).execute()


def get_all_settings() -> dict:
    sb = _get_client()
    res = sb.table("settings").select("key, value").execute()
    return {r["key"]: r["value"] for r in res.data}


# ── Account helpers ───────────────────────────────────────────
def add_account(phone: str, ss: str, pp: int | None = None) -> int:
    sb = _get_client()

    # تعداد کل اکانت‌ها برای تعیین شیفت
    count_res = sb.table("accounts").select("id", count="exact").execute()
    count = count_res.count or 0

    half = 75
    shift = "A" if (count // half) % 2 == 0 else "B"

    res = sb.table("accounts").insert({
        "phone":             phone,
        "session_encrypted": encrypt(ss),
        "proxy_port":        pp,
        "shift":             shift,
    }).execute()

    new_id = res.data[0]["id"]
    print(f"✅ اکانت {phone} اضافه شد → شیفت {shift} (شماره {count + 1})", flush=True)
    return new_id


def get_account(phone: str) -> dict | None:
    sb = _get_client()
    res = sb.table("accounts").select("*").eq("phone", phone).limit(1).execute()
    return res.data[0] if res and res.data else None


def get_all_accounts() -> list[dict]:
    sb = _get_client()
    res = sb.table("accounts").select("*").order("id").execute()
    return res.data


def get_accounts_by_shift(s: str) -> list[dict]:
    sb = _get_client()
    res = sb.table("accounts").select("*").eq("shift", s).execute()
    return res.data


def update_account_status(phone: str, status: str, error: str | None = None, until=None):
    sb = _get_client()
    payload: dict = {"status": status, "last_error": error}
    if until is not None:
        # until می‌تونه string یا datetime باشه
        payload["flood_until"] = until if isinstance(until, str) else until.isoformat()
    sb.table("accounts").update(payload).eq("phone", phone).execute()


def update_account_shift(phone: str, shift: str):
    sb = _get_client()
    sb.table("accounts").update({"shift": shift}).eq("phone", phone).execute()


def get_session(phone: str) -> str | None:
    a = get_account(phone)
    return decrypt(a["session_encrypted"]) if a else None


def delete_account(phone: str):
    sb = _get_client()
    sb.table("accounts").delete().eq("phone", phone).execute()


def count_by_status() -> dict:
    """
    Supabase از GROUP BY مستقیم پشتیبانی نمی‌کنه؛
    با یه کوئری ساده حساب می‌کنیم.
    """
    sb = _get_client()
    res = sb.table("accounts").select("status").execute()
    counts: dict = {}
    for row in res.data:
        s = row["status"]
        counts[s] = counts.get(s, 0) + 1
    return counts


# ── Debug log ─────────────────────────────────────────────────
def debug_log(module: str, step: str, status: str, message: str = ""):
    print(f"[{status}] {module}.{step}: {message}", flush=True)
    try:
        sb = _get_client()
        sb.table("debug_log").insert({
            "module":  module,
            "step":    step,
            "status":  status,
            "message": message,
        }).execute()
    except Exception as e:
        print(f"[LOG-FAIL] {e}", flush=True)
