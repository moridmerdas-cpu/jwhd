import asyncio, json, sqlite3, time, sys
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, '/root/tg_master_bot')
from config import Config
from models import database as db
from core.engine import make_client
from telethon import functions

LOG = Path("/root/tg_master_bot/logs/monitor.log")
DB = Path("/root/tg_master_bot/models/tg_system.db")
CHECK_INTERVAL = 300

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def ensure_tables():
    conn = sqlite3.connect(DB)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS monitor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            last_msg_id INTEGER,
            views INTEGER,
            accounts_ok INTEGER,
            accounts_flood INTEGER,
            active_shift INTEGER,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS rate_limit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_ts TEXT, end_ts TEXT, duration_sec INTEGER,
            views_at_start INTEGER, views_at_end INTEGER,
            reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
    finally:
        conn.close()

async def check_channel():
    db.init_db()
    accounts = db.get_all_accounts()
    if not accounts:
        return None
    c = make_client(db.get_session(accounts[0]["phone"]))
    try:
        await asyncio.wait_for(c.connect(), timeout=20)
        target = Config.TARGET_CHANNEL_ID or Config.TARGET_CHANNEL_USERNAME
        ch = await asyncio.wait_for(c.get_entity(target), timeout=15)
        msgs = await asyncio.wait_for(c.get_messages(ch, limit=1), timeout=10)
        if not msgs:
            return None
        msg_id = msgs[0].id
        r = await asyncio.wait_for(
            c(functions.messages.GetMessagesViewsRequest(peer=ch, id=[msg_id], increment=False)), timeout=10)
        views = r.views[0].views if r.views else 0
        await c.disconnect()
        return {"msg_id": msg_id, "views": views}
    except Exception as e:
        try:
            await c.disconnect()
        except Exception:
            pass
        return {"error": f"{type(e).__name__}: {str(e)[:50]}"}

def get_stats():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT status, COUNT(*) as cnt FROM accounts GROUP BY status").fetchall()
        return {r["status"]: r["cnt"] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()

def save_monitor(views, msg_id, shift):
    conn = sqlite3.connect(DB)
    try:
        conn.execute("""INSERT INTO monitor_data (ts,last_msg_id,views,active_shift,status)
                     VALUES (?,?,?,?,?)""",
                     (datetime.now().isoformat(), msg_id, views, shift,
                      "ok" if views > 0 else "no_views"))
        conn.commit()
    finally:
        conn.close()

def detect_rl(history):
    if len(history) < 3:
        return None
    last3 = history[-3:]
    if all(h["views"] <= 2 for h in last3) and len(history) >= 6:
        before = history[-6:-3]
        avg = sum(h["views"] for h in before) / 3
        if avg > 10:
            return {"start": last3[0]["ts"], "reason": f"views {avg:.0f}->{last3[-1]['views']}"}
    return None

async def notify_admin(msg):
    try:
        from aiogram import Bot
        bot = Bot(token=Config.BOT_TOKEN)
        for aid in Config.ADMIN_IDS:
            try:
                await bot.send_message(aid, f"📊 <b>Monitor</b>\n\n{msg}", parse_mode="HTML")
            except Exception:
                pass
        await bot.close()
    except Exception:
        pass

async def main():
    log("═" * 50)
    log("📊 TG Monitor 24/7")
    log("═" * 50)
    ensure_tables()
    history = []
    last_notify = 0
    while True:
        try:
            res = await check_channel()
            if not res or "error" in res:
                log(f"❌ {res.get('error', 'unknown') if res else 'None'}")
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            views = res["views"]
            msg_id = res["msg_id"]
            stats = get_stats()
            ok = stats.get("online", 0) + stats.get("idle", 0)
            flood = stats.get("flood", 0)
            try:
                from core.pool import POOL
                shift = POOL.active_shift
            except Exception:
                shift = 0
            save_monitor(views, msg_id, shift)
            history.append({"ts": datetime.now().isoformat(), "views": views, "msg_id": msg_id})
            if len(history) > 20:
                history = history[-20:]
            log(f"📊 msg={msg_id} views={views} shift={shift} ok={ok} flood={flood}")
            rl = detect_rl(history)
            if rl and time.time() - last_notify > 3600:
                last_notify = time.time()
                log(f"⚠️ RL: {rl['reason']}")
                await notify_admin(f"⚠️ Rate Limit\n{rl['reason']}\nviews: {views}")
        except Exception as e:
            log(f"❌ {type(e).__name__}: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
