import sqlite3, base64, hashlib, sys
from pathlib import Path
from cryptography.fernet import Fernet
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config

DB_PATH = Config.DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _get_fernet():
    kb = hashlib.sha256(Config.ENCRYPTION_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(kb))


FERNET = _get_fernet()
def encrypt(t): return FERNET.encrypt(t.encode()).decode()
def decrypt(t): return FERNET.decrypt(t.encode()).decode()


def get_conn():
    c = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init_db():
    c = get_conn()
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            session_encrypted TEXT NOT NULL,
            proxy_port INTEGER,
            status TEXT DEFAULT 'idle',
            shift TEXT DEFAULT 'A',
            flood_until TEXT,
            last_error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT UNIQUE NOT NULL,
            group_id TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS debug_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT, step TEXT, status TEXT, message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
    finally:
        c.close()
    print("✅ دیتابیس آماده شد")


def add_account(phone, ss, pp=None):
    """اضافه کردن اکانت + تعیین خودکار شیفت (A یا B) بر اساس تعداد موجود"""
    c = get_conn()
    try:
        # تعداد فعلی
        row = c.execute("SELECT COUNT(*) as cnt FROM accounts").fetchone()
        count = row["cnt"]
        # 0-74 → A, 75-149 → B, 150-224 → A, ...
        half = 75
        shift = "A" if (count // half) % 2 == 0 else "B"
        
        cur = c.execute(
            "INSERT INTO accounts (phone, session_encrypted, proxy_port, shift) VALUES (?, ?, ?, ?)",
            (phone, encrypt(ss), pp, shift))
        new_id = cur.lastrowid
        print(f"✅ اکانت {phone} اضافه شد → شیفت {shift} (شماره {count+1})", flush=True)
        return new_id
    finally:
        c.close()


def get_account(phone):
    c = get_conn()
    try:
        r = c.execute("SELECT * FROM accounts WHERE phone = ?", (phone,)).fetchone()
        return dict(r) if r else None
    finally: c.close()


def get_all_accounts():
    c = get_conn()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM accounts ORDER BY id").fetchall()]
    finally: c.close()


def get_accounts_by_shift(s):
    c = get_conn()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM accounts WHERE shift=?", (s,)).fetchall()]
    finally: c.close()


def update_account_status(phone, status, error=None, until=None):
    c = get_conn()
    try:
        c.execute("UPDATE accounts SET status=?, last_error=?, flood_until=?, updated_at=CURRENT_TIMESTAMP WHERE phone=?",
                  (status, error, until, phone))
    finally: c.close()


def update_account_shift(phone, shift):
    c = get_conn()
    try:
        c.execute("UPDATE accounts SET shift=? WHERE phone=?", (shift, phone))
    finally: c.close()


def get_session(phone):
    a = get_account(phone)
    return decrypt(a["session_encrypted"]) if a else None


def delete_account(phone):
    c = get_conn()
    try:
        c.execute("DELETE FROM accounts WHERE phone=?", (phone,))
    finally: c.close()


def count_by_status():
    c = get_conn()
    try:
        return {r["status"]: r["cnt"] for r in c.execute("SELECT status, COUNT(*) as cnt FROM accounts GROUP BY status").fetchall()}
    finally: c.close()


def add_channel(username, gid=None):
    c = get_conn()
    try:
        cur = c.execute("INSERT OR IGNORE INTO channels (channel_username, group_id) VALUES (?, ?)", (username, gid))
        return cur.lastrowid
    finally: c.close()


def get_active_channels():
    c = get_conn()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM channels WHERE active=1").fetchall()]
    finally: c.close()


def debug_log(module, step, status, message=""):
    print(f"[{status}] {module}.{step}: {message}", flush=True)
    try:
        c = get_conn()
        try:
            c.execute("INSERT INTO debug_log (module, step, status, message) VALUES (?, ?, ?, ?)",
                      (module, step, status, message))
        finally: c.close()
    except Exception as e:
        print(f"[LOG-FAIL] {e}", flush=True)
