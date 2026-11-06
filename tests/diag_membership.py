"""
چک می‌کنه هر اکانت عضو کانال هست یا نه
"""
import asyncio
import sys
sys.path.insert(0, '/root/tg_master_bot')

from config import Config
from models import database as db
from core.engine import make_client
from telethon import functions
from telethon.tl.types import ChannelParticipant


async def check_one(phone, target):
    ss = db.get_session(phone)
    if not ss:
        return phone, "NO_SESSION", "سشن نیست"

    c = make_client(ss)
    try:
        await asyncio.wait_for(c.connect(), timeout=20)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH", "مجاز نیست"

        me = await c.get_me()

        # چک عضویت
        try:
            ent = await asyncio.wait_for(c.get_entity(target), timeout=10)
        except Exception as e:
            await c.disconnect()
            return phone, "ENT_FAIL", f"{type(e).__name__}: {str(e)[:50]}"

        # چک participation
        try:
            # GetParticipant
            full = await asyncio.wait_for(c(functions.channels.GetParticipantRequest(
                channel=ent, participant=me)), timeout=10)
            role = type(full.participant).__name__
            await c.disconnect()
            return phone, "MEMBER", role
        except Exception as e:
            err = type(e).__name__
            if "UserNotParticipant" in err:
                await c.disconnect()
                return phone, "NOT_MEMBER", "عضو کانال نیست"
            await c.disconnect()
            return phone, "CHK_FAIL", f"{err}: {str(e)[:50]}"
    except Exception as e:
        try:
            await c.disconnect()
        except Exception:
            pass
        return phone, "OUTER_FAIL", f"{type(e).__name__}: {str(e)[:50]}"


async def main():
    db.init_db()
    print("█" * 70)
    print("  🔬 چک عضویت همه اکانت‌ها در کانال")
    print("█" * 70)

    accounts = db.get_all_accounts()
    print(f"📊 تعداد اکانت‌ها: {len(accounts)}")

    target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
    print(f"📢 کانال: {target}")

    print(f"\n⏳ در حال چک {len(accounts)} اکانت (ممکنه چند دقیقه طول بکشه)...")

    # موازی ۱۰ تا
    sem = asyncio.Semaphore(10)
    results = []

    async def one(acc):
        async with sem:
            r = await check_one(acc["phone"], target)
            results.append(r)
            return r

    await asyncio.gather(*[one(a) for a in accounts], return_exceptions=True)

    # شمارش
    from collections import Counter
    status_counts = Counter(r[1] for r in results)

    print("\n" + "═" * 70)
    print("📊 خلاصه:")
    print("═" * 70)
    for status, count in status_counts.most_common():
        emoji = {
            "MEMBER": "🟢",
            "NOT_MEMBER": "🔴",
            "NOT_AUTH": "⚫",
            "NO_SESSION": "⚫",
            "ENT_FAIL": "🟠",
            "CHK_FAIL": "🟡",
            "OUTER_FAIL": "🟣",
        }.get(status, "❔")
        print(f"  {emoji} {status}: {count}")

    # نمونه‌های هر دسته
    print("\n" + "═" * 70)
    print("🔍 نمونه ۳ اکانت از هر دسته:")
    print("═" * 70)

    shown = set()
    for phone, status, detail in results:
        if status in shown:
            continue
        shown.add(status)
        print(f"\n  {status}:")
        count = 0
        for p, s, d in results:
            if s == status and count < 3:
                print(f"    {p}: {d}")
                count += 1


if __name__ == "__main__":
    asyncio.run(main())
