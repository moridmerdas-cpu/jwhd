"""
models/database.py  —  نسخه Supabase
جایگزین کامل SQLite — همه signature ها سازگار هستن.
"""
import base64, hashlib, sys
from pathlib import Path
from cryptography.fernet import Fernet
from supabase import create_client, Client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config

# ── Supabase singleton ────────────────────────────────────────
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
    """جداول از قبل در Supabase ساخته شدن — فقط مقادیر پیش‌فرض رو ست می‌کنه."""
    sb = _get_client()
    defaults = {
        "target_group_id":   str(Config.TARGET_GROUP_ID),
        "shift_min_sec":     str(Config.SHIFT_MIN_SEC),
        "shift_max_sec":     str(Config.SHIFT_MAX_SEC),
        "active_shift":      "1",
        "auto_view_enabled": "1",
    }
    for key, value in defaults.items():
        sb.table("settings").upsert(
            {"key": key, "value": value},
            ignore_duplicates=True
        ).execute()
    print("✅ Supabase آماده شد")


# ── migrate: شیفت A/B/C/D → 1/2/3/4 ─────────────────────────
def migrate_shifts():
    """یه‌بار اجرا میشه — شیفت‌های legacy رو تبدیل می‌کنه."""
    sb = _get_client()
    legacy_map = {"A": "1", "B": "2", "C": "3", "D": "4"}
    for old, new in legacy_map.items():
        sb.table("accounts").update({"shift": new}).eq("shift", old).execute()
    print("✅ مایگریشن شیفت انجام شد (A/B/C/D → 1/2/3/4)")


# ── Settings helpers ──────────────────────────────────────────
def get_setting(key: str, default=None):
    sb = _get_client()
    res = sb.table("settings").select("value").eq("key", key).maybe_single().execute()
    return res.data["value"] if res.data else default


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
    count_res = sb.table("accounts").select("id", count="exact").execute()
    count = count_res.count or 0
    shift = str((count % 4) + 1)   # شیفت عددی 1-4 هماهنگ با pool.py
    res = sb.table("accounts").insert({
        "phone":             phone,
        "session_encrypted": encrypt(ss),
        "proxy_port":        pp,
        "shift":             shift,
        "status":            "idle",
    }).execute()
    new_id = res.data[0]["id"]
    print(f"✅ اکانت {phone} اضافه شد → شیفت {shift} (شماره {count + 1})", flush=True)
    return new_id


def get_account(phone: str) -> dict | None:
    sb = _get_client()
    res = sb.table("accounts").select("*").eq("phone", phone).maybe_single().execute()
    return res.data or None


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


# ── Supabase stats helpers (جایگزین raw SQL) ─────────────────
def count_debug_log_since(step: str, hours: int = 24) -> int:
    """تعداد رکوردهای debug_log در N ساعت گذشته"""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    sb = _get_client()
    res = sb.table("debug_log").select("id", count="exact").eq("step", step).gte("created_at", since).execute()
    return res.count or 0


def chart_reads_last_12h() -> list[dict]:
    """آمار ویوها در ۱۲ ساعت گذشته — جایگزین GROUP BY SQL"""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    sb = _get_client()
    res = sb.table("debug_log").select("created_at").eq("step", "read_done").eq("status", "RESULT").gte("created_at", since).execute()
    # group by hour in Python
    counts: dict = {}
    for row in res.data:
        h = str(row["created_at"])[11:13]
        counts[h] = counts.get(h, 0) + 1
    return [{"h": h, "ok": c} for h, c in sorted(counts.items())]


# ── stub برای compatibility — get_conn حذف شده ───────────────
def get_conn():
    raise RuntimeError(
        "get_conn() در نسخه Supabase وجود نداره. "
        "از db.count_debug_log_since() و db.chart_reads_last_12h() استفاده کن."
    )
