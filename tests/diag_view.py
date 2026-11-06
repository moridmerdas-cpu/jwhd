"""
تست view با پیام موجود — خطای دقیق هر اکانت
"""
import asyncio
import sys
import traceback
from collections import Counter
sys.path.insert(0, '/root/tg_master_bot')

from config import Config
from models import database as db
from core.engine import make_client
from telethon import functions
from telethon.errors import FloodWaitError


async def test_one(phone, target, msg_id):
    """تست view با یه اکانت"""
    ss = db.get_session(phone)
    if not ss:
        return phone, "NO_SESSION", ""

    c = make_client(ss)
    try:
        await asyncio.wait_for(c.connect(), timeout=20)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH", ""

        # get_entity با username
        try:
            ent = await asyncio.wait_for(
                c.get_entity(target), timeout=10)
        except Exception as e:
            await c.disconnect()
            return phone, f"ENT_ERR", f"{type(e).__name__}: {str(e)[:60]}"

        # view با entity
        try:
            r = await asyncio.wait_for(
                c(functions.messages.GetMessagesViewsRequest(
                    peer=ent, id=[msg_id], increment=True)),
                timeout=15
            )
            views = r.views[0].views if r.views else "?"
            await c.disconnect()
            return phone, "OK", f"views={views}"
        except FloodWaitError as e:
            await c.disconnect()
            return phone, "FLOOD", f"{e.seconds}s"
        except Exception as e:
            await c.disconnect()
            return phone, f"VIEW_ERR", f"{type(e).__name__}: {str(e)[:60]}"
    except Exception as e:
        try:
            await c.disconnect()
        except Exception:
            pass
        return phone, "OUTER", f"{type(e).__name__}: {str(e)[:60]}"


async def main():
    db.init_db()
    print("█" * 70)
    print("  🔬 تست view روی پیام موجود")
    print("█" * 70)

    accounts = db.get_all_accounts()
    target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID

    # یه اکانت برای پیدا کردن آخرین پیام
    admin_ss = db.get_session(accounts[0]["phone"])
    c = make_client(admin_ss)
    await c.connect()
    ch = await c.get_entity(target)
    msgs = await c.get_messages(ch, limit=1)
    msg_id = msgs[0].id
    print(f"\n📩 پیام تست: ID={msg_id}")

    # views قبل
    try:
        r = await c(functions.messages.GetMessagesViewsRequest(
            peer=ch, id=[msg_id], increment=False))
        before = r.views[0].views if r.views else "?"
        print(f"📊 views قبل: {before}")
    except Exception as e:
        print(f"❌ خواندن views قبل: {e}")
        before = "?"

    await c.disconnect()

    # ═══ تست با ۱۰ اکانت ═══
    sample = accounts[:10]
    print(f"\n⏳ تست با {len(sample)} اکانت...")

    results = []
    for acc in sample:
        r = await test_one(acc["phone"], target, msg_id)
        results.append(r)
        emoji = "✅" if r[1] == "OK" else "❌"
        print(f"  {emoji} {r[0]}: {r[1]} | {r[2]}")

    # شمارش
    print("\n" + "═" * 70)
    print("📊 خلاصه:")
    print("═" * 70)
    counts = Counter(r[1] for r in results)
    for status, n in counts.most_common():
        print(f"  {status}: {n}")

    # ═══ views بعد (با ۵ ثانیه صبر) ═══
    print(f"\n⏳ صبر ۵ ثانیه...")
    await asyncio.sleep(5)

    c = make_client(admin_ss)
    await c.connect()
    ch = await c.get_entity(target)
    try:
        r = await c(functions.messages.GetMessagesViewsRequest(
            peer=ch, id=[msg_id], increment=False))
        after = r.views[0].views if r.views else "?"
        print(f"📊 views بعد: {after}")
        print(f"📊 اختلاف: {after} - {before} = {int(after) - int(before) if isinstance(after, int) and isinstance(before, int) else '?'}")
    except Exception as e:
        print(f"❌ {e}")

    await c.disconnect()
    print("█" * 70)


if __name__ == "__main__":
    asyncio.run(main())
