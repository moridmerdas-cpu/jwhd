"""Fast Joiner — همه اکانت‌ها سریع join بشن"""
import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime
from collections import Counter

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
CONCURRENCY = 5        # ۵ اکانت همزمان
DELAY_BETWEEN = 3      # ۳ ثانیه بین هر join

STATE_FILE = Path("/root/tg_master_bot/proxies/join_state.json")
LOG_FILE = Path("/root/tg_master_bot/logs/fast_joiner.log")


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
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
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    except Exception as e:
        log(f"⚠️ save_state: {e}")


async def try_join(phone):
    ss = db.get_session(phone)
    if not ss:
        return phone, "NO_SESSION"

    c = make_client(ss, phone=phone)
    try:
        await asyncio.wait_for(c.connect(), timeout=25)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH"

        # چک قبلی
        try:
            await asyncio.wait_for(
                c.get_entity(TARGET_USERNAME), timeout=10)
            await c.disconnect()
            return phone, "ALREADY_MEMBER"
        except Exception:
            pass

        # Join
        try:
            await asyncio.wait_for(
                c(functions.channels.JoinChannelRequest(channel=TARGET_USERNAME)),
                timeout=20
            )
            await asyncio.sleep(0.5)
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
            await c.disconnect()
            return phone, f"ERR:{type(e).__name__}"

    except Exception as e:
        try:
            await c.disconnect()
        except Exception:
            pass
        return phone, f"OUTER:{type(e).__name__}"


async def main():
    log("═" * 60)
    log(f"🚀 Fast Joiner شروع")
    log(f"📢 Target: @{TARGET_USERNAME}")
    log(f"⚡ Concurrency: {CONCURRENCY} | Delay: {DELAY_BETWEEN}s")
    log("═" * 60)

    db.init_db()
    state = load_state()

    accounts = db.get_all_accounts()
    total = len(accounts)
    joined_set = set(state.get("joined", []))
    failed_map = state.get("failed", {})

    # فیلتر: dead skip، joined skip، 3+ fail skip
    todo = []
    for acc in accounts:
        phone = acc["phone"]
        if acc.get("status") == "dead":
            continue
        if phone in joined_set:
            continue
        if failed_map.get(phone, 0) >= 3:
            continue
        todo.append(phone)

    log(f"📊 کل اکانت: {total}")
    log(f"✅ قبلاً join: {len(joined_set)}")
    log(f"🎯 باقی‌مانده: {len(todo)}")

    if not todo:
        log("🎉 همه join شده‌ن!")
        return

    # ═══ اجرای موازی با semaphore ═══
    sem = asyncio.Semaphore(CONCURRENCY)
    results = Counter()

    async def one(phone, idx):
        async with sem:
            log(f"[{idx}/{len(todo)}] ▶️ {phone}")
            _, result = await try_join(phone)
            results[result] = results.get(result, 0) + 1

            if result in ("JOINED", "ALREADY_MEMBER"):
                if phone not in state["joined"]:
                    state["joined"].append(phone)
                state.get("failed", {}).pop(phone, None)
                log(f"   ✅ {phone}: {result}")
            elif result.startswith("FLOOD:"):
                log(f"   🟡 {phone}: {result} (صبر می‌کنم)")
            else:
                failed = state.get("failed", {})
                failed[phone] = failed.get(phone, 0) + 1
                state["failed"] = failed
                log(f"   ❌ {phone}: {result} (fail#{failed[phone]})")

            save_state(state)
            await asyncio.sleep(DELAY_BETWEEN)

    # اجرا
    tasks = [asyncio.create_task(one(p, i+1)) for i, p in enumerate(todo)]
    await asyncio.gather(*tasks, return_exceptions=True)

    log("═" * 60)
    log("📊 خلاصه نهایی:")
    for r, n in results.most_common():
        log(f"   {r}: {n}")
    log(f"✅ مجموع join شده: {len(state['joined'])}")
    log("═" * 60)


if __name__ == "__main__":
    asyncio.run(main())
