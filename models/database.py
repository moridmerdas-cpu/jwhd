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
    """هر اکانتی که شیفتش 1..4 نیست (A/B/C/D قدیمی یا خالی) رو بین ۴ شیفت متعادل پخش می‌کنه."""
    sb = _get_client()
    rows = sb.table("accounts").select("id, phone, shift").order("id").execute().data or []
    buckets = {"1": 0, "2": 0, "3": 0, "4": 0}
    legacy = []
    for r in rows:
        sh = str(r.get("shift") or "")
        if sh in buckets:
            buckets[sh] += 1
        else:
            legacy.append(r["phone"])
    for phone in legacy:
        target = min(buckets, key=lambda k: buckets[k])
        sb.table("accounts").update({"shift": target}).eq("phone", phone).execute()
        buckets[target] += 1
    if legacy:
        print(f"✅ مایگریشن شیفت: {len(legacy)} اکانت → {buckets}", flush=True)


def set_status_bulk(phones: list, status: str, only_from=("online", "idle")):
    """وضعیت چند اکانت رو با چند درخواست دسته‌ای عوض می‌کنه، بدون دست‌زدن به flood/error."""
    if not phones:
        return
    sb = _get_client()
    for i in range(0, len(phones), 100):
        chunk = phones[i:i + 100]
        sb.table("accounts").update({"status": status}) \
          .in_("phone", chunk).in_("status", list(only_from)).execute()


# ── Settings helpers ──────────────────────────────────────────
def get_setting(key: str, default=None):
    sb = _get_client()
    res = sb.table("settings").select("value").eq("key", key).limit(1).execute()
    return res.data[0]["value"] if res and res.data else default


def set_setting(key: str, value):
    sb = _get_client()
    sb.table("settings").upsert({"key": key, "value": str(value)}).execute()


def get_all_settings() -> dict:
    sb = _get_client()
    res = sb.table("settings").select("key, value").execute()
    return {r["key"]: r["value"] for r in res.data}


# ── Group ref: یوزرنیم یا آیدی عددی، منبع واحد ────────────────
import re as _re
_USERNAME_RE = _re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_group_id(n: int) -> int:
    """آیدی سوپرگروه/کانال همیشه -100xxxxxxxxxx ـه. اگه منفی‌ش افتاده باشه (1004488904522) درستش می‌کنه."""
    n = int(n or 0)
    if n > 0 and str(n).startswith("100") and len(str(n)) >= 12:
        return -n
    return n


def parse_group_ref(raw):
    """ورودی کاربر رو به یوزرنیم (str) یا آیدی عددی (int) تبدیل می‌کنه. نامعتبر => None.
    قبول می‌کنه: @name | name | t.me/name | https://t.me/name | t.me/c/123/45 | -100123... | 100123..."""
    s = str(raw or "").strip().translate(_FA_DIGITS).strip("/ ")
    if not s:
        return None
    m = _re.match(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/c/(\d+)(?:/\d+)*/?$", s, _re.I)
    if m:
        return int(f"-100{m.group(1)}")
    m = _re.match(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(.+)$", s, _re.I)
    if m:
        part = m.group(1).split("?")[0].split("/")[0]
        if part.startswith("+") or part.lower() == "joinchat":
            return None                      # لینک دعوت خصوصی
        s = part
    s = s.lstrip("@")
    if _re.fullmatch(r"-?\d+", s):
        n = normalize_group_id(int(s))
        return n or None
    return s if _USERNAME_RE.match(s) else None


def fmt_group(ref) -> str:
    if not ref:
        return "تنظیم نشده"
    return f"@{ref}" if isinstance(ref, str) else str(ref)


def get_target_group():
    """اول تنظیم ربات (دیتابیس)، اگه نبود env. خروجی: str (یوزرنیم) یا int (آیدی) یا 0."""
    v = get_setting("target_group_id", 0)
    ref = parse_group_ref(v) if v not in (None, "", 0, "0") else None
    if not ref:
        ref = parse_group_ref(getattr(Config, "TARGET_GROUP_ID", 0)) or 0
    return ref


get_target_group_id = get_target_group      # سازگاری با کدهای قبلی


# ── Account helpers ───────────────────────────────────────────
def add_account(phone: str, ss: str, pp: int | None = None) -> int:
    sb = _get_client()
    count_res = sb.table("accounts").select("id", count="exact").execute()
    count = count_res.count or 0
    # تعداد شیفت‌ها رو از db بخون (پیش‌فرض ۴)
    try:
        _ns = int(get_setting("num_shifts", 4) or 4)
        _ns = max(1, min(_ns, 20))
    except Exception:
        _ns = 4
    shift = str((count % _ns) + 1)
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


# ── Debug log (در thread جدا، حلقه‌ی asyncio رو قفل نمی‌کنه) ───
import threading as _threading
import queue as _queue

_LOGQ: "_queue.Queue" = _queue.Queue(maxsize=2000)
_log_thread = None
_log_lock = _threading.Lock()


def _log_worker():
    sb = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)   # کلاینت جدا برای thread
    while True:
        row = _LOGQ.get()
        try:
            sb.table("debug_log").insert(row).execute()
        except Exception as e:
            print(f"[LOG-FAIL] {e}", flush=True)


def debug_log(module: str, step: str, status: str, message: str = ""):
    global _log_thread
    print(f"[{status}] {module}.{step}: {message}", flush=True)
    with _log_lock:
        if _log_thread is None:
            _log_thread = _threading.Thread(target=_log_worker, daemon=True, name="debug-log")
            _log_thread.start()
    try:
        _LOGQ.put_nowait({"module": module, "step": step, "status": status, "message": message})
    except _queue.Full:
        pass


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
