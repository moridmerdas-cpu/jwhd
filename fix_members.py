"""Join اکانت‌های غیر-عضو به کانال"""
import asyncio, sys
sys.path.insert(0, '/root/tg_master_bot')
from config import Config
from models import database as db
from core.engine import make_client
from telethon import functions
from telethon.tl.types import Channel


async def try_join(phone, target):
    """تلاش برای عضویت"""
    c = make_client(db.get_session(phone), phone=phone)
    try:
        await asyncio.wait_for(c.connect(), timeout=20)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH"

        # چک کنیم آیا resolve می‌کنه
        try:
            ent = await asyncio.wait_for(c.get_entity(target), timeout=10)
            await c.disconnect()
            return phone, "ALREADY_MEMBER"
        except Exception:
            pass

        # تلاش برای join
        target_str = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID

        # اگه username داریم
        if Config.TARGET_CHANNEL_USERNAME:
            try:
                await asyncio.wait_for(
                    c(functions.channels.JoinChannelRequest(
                        channel=Config.TARGET_CHANNEL_USERNAME)),
                    timeout=15)
                await asyncio.sleep(1)
                ent = await asyncio.wait_for(c.get_entity(target), timeout=10)
                await c.disconnect()
                return phone, "JOINED"
            except Exception as e:
                err = type(e).__name__
                await c.disconnect()
                return phone, f"JOIN_FAIL:{err}"

        # اگه فقط ID داریم، سعی کنیم input_entity بگیریم
        try:
            # از channel_id خام
            target_id = Config.TARGET_CHANNEL_ID
            await asyncio.wait_for(
                c(functions.channels.JoinChannelRequest(channel=target_id)),
                timeout=15)
            await asyncio.sleep(1)
            await c.disconnect()
            return phone, "JOINED_BY_ID"
        except Exception as e:
            err = type(e).__name__
            await c.disconnect()
            return phone, f"JOIN_FAIL:{err}"

    except Exception as e:
        try:
            await c.disconnect()
        except: pass
        return phone, f"ERR:{type(e).__name__}"


async def main():
    db.init_db()
    accounts = db.get_all_accounts()
    target = Config.TARGET_CHANNEL_ID or Config.TARGET_CHANNEL_USERNAME

    print(f"📢 Target: {target}")
    print(f"👥 {len(accounts)} اکانت")

    # فقط اکانت‌هایی که resolve نمی‌کنن
    print("⏳ شناسایی غیر-عضوها...")

    non_members = []
    sem = asyncio.Semaphore(20)

    async def check(acc):
        async with sem:
            c = make_client(db.get_session(acc["phone"]), phone=acc["phone"])
            try:
                await asyncio.wait_for(c.connect(), timeout=15)
                try:
                    await asyncio.wait_for(c.get_entity(target), timeout=8)
                    await c.disconnect()
                    return (acc["phone"], "MEMBER")
                except Exception:
                    await c.disconnect()
                    return (acc["phone"], "NON_MEMBER")
            except Exception:
                try: await c.disconnect()
                except: pass
                return (acc["phone"], "ERR")

    results = await asyncio.gather(*[check(a) for a in accounts])
    non_members = [r[0] for r in results if r[1] == "NON_MEMBER"]
    members = [r[0] for r in results if r[1] == "MEMBER"]

    print(f"✅ عضو: {len(members)}")
    print(f"❌ غیر-عضو: {len(non_members)}")

    if not non_members:
        print("🎉 همه عضو هستن!")
        return

    # ═══ Join non-members ═══
    print(f"\n⏳ Join {len(non_members)} اکانت به کانال...")
    print(f"   (target: {target})")

    join_sem = asyncio.Semaphore(3)  # کم برای جلوگیری از flood
    joined = 0
    failed = 0

    async def do_join(phone):
        nonlocal joined, failed
        async with join_sem:
            _, result = await try_join(phone, target)
            if result in ("JOINED", "JOINED_BY_ID", "ALREADY_MEMBER"):
                joined += 1
                print(f"  ✅ {phone}: {result}")
            else:
                failed += 1
                print(f"  ❌ {phone}: {result}")
            await asyncio.sleep(2)  # صبر بین joinها

    await asyncio.gather(*[do_join(p) for p in non_members])

    print(f"\n{'═'*50}")
    print(f"  ✅ joined: {joined}")
    print(f"  ❌ failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
