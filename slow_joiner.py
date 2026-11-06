"""
Slow Joiner — هر 5 دقیقه 1 اکانت وارد گروه می‌شه
- State در JSON (کدوم اکانت join شده)
- خطاها لاگ می‌شن
- Self-Healing: هر 5 دقیقه 1 اکانت
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/root/tg_master_bot')
from models import database as db
from core.engine import make_client
from telethon import functions
from telethon.errors import (
    UserAlreadyParticipantError,
    FloodWaitError,
    ChannelPrivateError,
    InviteRequestSentError,
    UserBannedInChannelError,
)

TARGET_USERNAME = "tabligeazade"
JOIN_INTERVAL = 300  # 5 دقیقه

STATE_FILE = Path("/root/tg_master_bot/proxies/join_state.json")
LOG_FILE = Path("/root/tg_master_bot/logs/slow_joiner.log")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"joined": [], "failed": {}, "started_at": datetime.now().isoformat()}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    except Exception as e:
        log(f"⚠️ save_state: {e}")


async def try_join(phone):
    """تلاش برای join"""
    ss = db.get_session(phone)
    if not ss:
        return phone, "NO_SESSION"

    c = make_client(ss, phone=phone)
    try:
        await asyncio.wait_for(c.connect(), timeout=25)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH"

        # چک کن قبلاً عضو هست یا نه
        try:
            await asyncio.wait_for(
                c.get_entity(TARGET_USERNAME), timeout=10)
            await c.disconnect()
            return phone, "ALREADY_MEMBER"
        except Exception:
            pass

        # تلاش برای join
        try:
            await asyncio.wait_for(
                c(functions.channels.JoinChannelRequest(channel=TARGET_USERNAME)),
                timeout=20
            )
            await asyncio.sleep(1)
            await c.disconnect()
            return phone, "JOINED"
        except UserAlreadyParticipantError:
            await c.disconnect()
            return phone, "ALREADY_MEMBER"
        except UserBannedInChannelError:
            await c.disconnect()
            return phone, "BANNED"
        except ChannelPrivateError:
            await c.disconnect()
            return phone, "PRIVATE"
        except InviteRequestSentError:
            await c.disconnect()
            return phone, "REQUEST_SENT"
        except FloodWaitError as e:
            await c.disconnect()
            return phone, f"FLOOD:{e.seconds}"
        except Exception as e:
            err = type(e).__name__
            await c.disconnect()
            return phone, f"ERR:{err}"

    except Exception as e:
        try:
            await c.disconnect()
        except Exception:
            pass
        return phone, f"OUTER:{type(e).__name__}"


async def pick_next_account(state):
    """پیدا کردن اکانت بعدی که join نشده"""
    db.init_db()
    accounts = db.get_all_accounts()

    joined_set = set(state.get("joined", []))
    failed_map = state.get("failed", {})

    for acc in accounts:
        phone = acc["phone"]
        if acc.get("status") == "dead":
            continue
        if phone in joined_set:
            continue
        # اگه قبلاً fail شده و 3 بار fail داشته، skip کن
        if failed_map.get(phone, 0) >= 3:
            continue
        return phone

    return None


async def main():
    log("═" * 60)
    log(f"🚀 Slow Joiner شروع — هر {JOIN_INTERVAL}s یک اکانت")
    log(f"📢 Target: @{TARGET_USERNAME}")
    log("═" * 60)

    db.init_db()
    state = load_state()

    total_accounts = len(db.get_all_accounts())
    log(f"📊 کل اکانت‌ها: {total_accounts}")
    log(f"✅ قبلاً join شده: {len(state.get('joined', []))}")

    cycle = 0
    while True:
        cycle += 1
        try:
            phone = await pick_next_account(state)

            if phone is None:
                log(f"🎉 همه اکانت‌ها join شدن یا fail کردن! تموم شد.")
                log(f"   موفق: {len(state.get('joined', []))}")
                log(f"   fail: {len(state.get('failed', {}))}")
                break

            log(f"▶️ [{cycle}] تلاش با {phone}...")
            _, result = await try_join(phone)
            log(f"   نتیجه: {result}")

            if result in ("JOINED", "ALREADY_MEMBER"):
                if phone not in state["joined"]:
                    state["joined"].append(phone)
                # از failed پاک کن
                state.get("failed", {}).pop(phone, None)
            elif result.startswith("FLOOD:"):
                # flood — صبر بیشتر
                sec = int(result.split(":")[1])
                log(f"   🟡 FloodWait {sec}s — صبر می‌کنم")
            else:
                # fail — افزایش شمارنده
                failed = state.get("failed", {})
                failed[phone] = failed.get(phone, 0) + 1
                state["failed"] = failed

            save_state(state)

            # خلاصه
            log(f"   📊 موفق: {len(state['joined'])}/{total_accounts}")

        except Exception as e:
            log(f"❌ چرخه {cycle}: {type(e).__name__}: {e}")

        # صبر 5 دقیقه
        log(f"   💤 صبر {JOIN_INTERVAL}s...")
        await asyncio.sleep(JOIN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
