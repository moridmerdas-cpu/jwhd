"""
تست ۳۶۰ درجه — تشخیص دقیق مشکل view
"""
import asyncio
import sys
import traceback
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/root/tg_master_bot')

from config import Config
from models import database as db
from core.engine import make_client, instant_view
from telethon import functions
from telethon.errors import FloodWaitError, ChannelInvalidError, PeerIdInvalidError


async def main():
    db.init_db()
    print("█" * 70)
    print("  🔬 تست ۳۶۰ درجه")
    print("█" * 70)

    accounts = db.get_all_accounts()
    print(f"\n📊 تعداد اکانت‌ها: {len(accounts)}")

    if not accounts:
        print("❌ اکانتی نیست")
        return

    target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
    print(f"📢 کانال هدف: {target}")
    print(f"   TARGET_CHANNEL_ID: {Config.TARGET_CHANNEL_ID}")
    print(f"   TARGET_CHANNEL_USERNAME: {Config.TARGET_CHANNEL_USERNAME}")

    # ═══ مرحله ۱: یه اکانت به‌عنوان ادمین، یه پیام جدید بذار ═══
    print("\n" + "═" * 70)
    print("مرحله ۱: ارسال پیام تستی از ادمین")
    print("═" * 70)

    admin_acc = accounts[0]
    admin_phone = admin_acc["phone"]
    admin_ss = db.get_session(admin_phone)
    if not admin_ss:
        print(f"❌ سشن {admin_phone} نیست")
        return

    admin_client = make_client(admin_ss)
    await admin_client.connect()

    if not await admin_client.is_user_authorized():
        print(f"❌ {admin_phone} مجاز نیست")
        await admin_client.disconnect()
        return

    me = await admin_client.get_me()
    print(f"👤 ادمین: {admin_phone} → @{me.username or me.first_name}")

    # پیدا کردن کانال
    try:
        ch = await admin_client.get_entity(target)
        print(f"✅ کانال پیدا شد: {ch.title} | id={ch.id}")
    except Exception as e:
        print(f"❌ کانال پیدا نشد: {type(e).__name__}: {e}")
        traceback.print_exc()
        await admin_client.disconnect()
        return

    # ارسال پیام
    try:
        sent = await admin_client.send_message(ch, f"تست دیاگ {datetime.now().strftime('%H:%M:%S')}")
        print(f"✅ پیام ارسال شد: ID={sent.id}")
        msg_id = sent.id
    except Exception as e:
        print(f"❌ ارسال fail: {type(e).__name__}: {e}")
        traceback.print_exc()
        await admin_client.disconnect()
        return

    await asyncio.sleep(3)

    # ═══ مرحله ۲: peer_id درست چیه؟ ═══
    print("\n" + "═" * 70)
    print("مرحله ۲: تست peer_id")
    print("═" * 70)

    # حالت‌های مختلف peer
    peer_variants = [
        ("channel_entity", ch),
        ("int_minus_100", -1000000000000 - ch.id),
        ("Config.TARGET_CHANNEL_ID", Config.TARGET_CHANNEL_ID),
        ("username", Config.TARGET_CHANNEL_USERNAME),
    ]

    for name, peer in peer_variants:
        try:
            r = await asyncio.wait_for(
                admin_client(functions.messages.GetMessagesViewsRequest(
                    peer=peer, id=[msg_id], increment=False)),
                timeout=10
            )
            views = r.views[0].views if r.views else "?"
            print(f"  ✅ {name}: views={views}")
        except Exception as e:
            print(f"  ❌ {name}: {type(e).__name__}: {str(e)[:80]}")

    # ═══ مرحله ۳: با هر اکانت جداگانه امتحان کن ═══
    print("\n" + "═" * 70)
    print("مرحله ۳: تست سین با ۵ اکانت مختلف")
    print("═" * 70)

    # ۵ اکانت نمونه (شامل ادمین)
    sample = accounts[:5]
    results = {"OK": 0, "FAIL": 0}

    for acc in sample:
        phone = acc["phone"]
        ss = db.get_session(phone)
        if not ss:
            print(f"  ❌ {phone}: سشن نیست")
            results["FAIL"] += 1
            continue

        c = make_client(ss)
        try:
            await asyncio.wait_for(c.connect(), timeout=20)
            if not await c.is_user_authorized():
                print(f"  ❌ {phone}: مجاز نیست")
                results["FAIL"] += 1
                await c.disconnect()
                continue

            # امتحان با channel_entity
            try:
                ent = await asyncio.wait_for(c.get_entity(Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID), timeout=10)
            except Exception as e:
                print(f"  ❌ {phone}: get_entity fail: {type(e).__name__}: {str(e)[:60]}")
                results["FAIL"] += 1
                await c.disconnect()
                continue

            # سین
            try:
                r = await asyncio.wait_for(
                    c(functions.messages.GetMessagesViewsRequest(
                        peer=ent, id=[msg_id], increment=True)),
                    timeout=15
                )
                views = r.views[0].views if r.views else "?"
                print(f"  ✅ {phone}: view OK | views={views}")
                results["OK"] += 1
            except FloodWaitError as e:
                print(f"  🟡 {phone}: FloodWait {e.seconds}s")
                results["FAIL"] += 1
            except Exception as e:
                print(f"  ❌ {phone}: view fail: {type(e).__name__}: {str(e)[:80]}")
                results["FAIL"] += 1
        except Exception as e:
            print(f"  ❌ {phone}: OUTER: {type(e).__name__}: {str(e)[:60]}")
            results["FAIL"] += 1
        finally:
            try:
                await c.disconnect()
            except Exception:
                pass

    # ═══ مرحله ۴: چک views فعلی ═══
    print("\n" + "═" * 70)
    print("مرحله ۴: views نهایی")
    print("═" * 70)

    await asyncio.sleep(3)
    try:
        r = await admin_client(functions.messages.GetMessagesViewsRequest(
            peer=ch, id=[msg_id], increment=False))
        views = r.views[0].views if r.views else "?"
        print(f"📊 views پیام {msg_id}: {views}")
    except Exception as e:
        print(f"❌ {e}")

    # ═══ خلاصه ═══
    print("\n" + "█" * 70)
    print(f"  ✅ موفق: {results['OK']}  |  ❌ fail: {results['FAIL']}")
    print("█" * 70)

    await admin_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
