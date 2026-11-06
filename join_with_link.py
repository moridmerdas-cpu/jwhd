"""Join اکانت‌های غیر-عضو با invite link"""
import asyncio, sys
sys.path.insert(0, '/root/tg_master_bot')
from config import Config
from models import database as db
from core.engine import make_client
from telethon import functions
from telethon.errors import UserAlreadyParticipantError, InviteHashExpiredError, InviteHashInvalidError


# ═══ لینک دعوت ═══
INVITE_HASH = "PNH1ajb8n6FmN2Zk"
TARGET_CHANNEL = "-1004441267101"


async def check_member(phone):
    """آیا عضو هست؟"""
    c = make_client(db.get_session(phone), phone=phone)
    try:
        await asyncio.wait_for(c.connect(), timeout=15)
        try:
            await asyncio.wait_for(c.get_entity(int(TARGET_CHANNEL)), timeout=8)
            await c.disconnect()
            return True
        except Exception:
            await c.disconnect()
            return False
    except Exception:
        try: await c.disconnect()
        except: pass
        return None


async def join_one(phone):
    """Join با invite hash"""
    c = make_client(db.get_session(phone), phone=phone)
    try:
        await asyncio.wait_for(c.connect(), timeout=20)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH"

        # چک اول — شاید قبلاً عضو شده
        try:
            await asyncio.wait_for(c.get_entity(int(TARGET_CHANNEL)), timeout=8)
            await c.disconnect()
            return phone, "ALREADY_MEMBER"
        except Exception:
            pass

        # Join با hash
        try:
            result = await asyncio.wait_for(
                c(functions.messages.ImportChatInviteRequest(hash=INVITE_HASH)),
                timeout=20
            )
            await asyncio.sleep(2)
            await c.disconnect()
            return phone, "JOINED"
        except UserAlreadyParticipantError:
            await c.disconnect()
            return phone, "ALREADY_MEMBER"
        except InviteHashExpiredError:
            await c.disconnect()
            return phone, "HASH_EXPIRED"
        except InviteHashInvalidError:
            await c.disconnect()
            return phone, "HASH_INVALID"
        except Exception as e:
            err = type(e).__name__
            await c.disconnect()
            return phone, f"ERR:{err}"
    except Exception as e:
        try: await c.disconnect()
        except: pass
        return phone, f"OUTER:{type(e).__name__}"


async def main():
    db.init_db()
    accounts = db.get_all_accounts()
    print(f"👥 کل: {len(accounts)}")
    print(f"🔗 hash: {INVITE_HASH}")
    print(f"📢 channel: {TARGET_CHANNEL}")

    # ═══ مرحله ۱: شناسایی غیر-عضوها ═══
    print("\n⏳ شناسایی غیر-عضوها...")
    sem = asyncio.Semaphore(20)
    results = {}

    async def check(acc):
        async with sem:
            r = await check_member(acc["phone"])
            results[acc["phone"]] = r

    await asyncio.gather(*[check(a) for a in accounts])

    members = [p for p, r in results.items() if r is True]
    non_members = [p for p, r in results.items() if r is False]
    errors = [p for p, r in results.items() if r is None]

    print(f"✅ عضو: {len(members)}")
    print(f"❌ غیر-عضو: {len(non_members)}")
    print(f"⚠️ خطا: {len(errors)}")

    if not non_members:
        print("\n🎉 همه عضو هستن!")
        return

    # ═══ مرحله ۲: Join non-members ═══
    print(f"\n⏳ Join {len(non_members)} اکانت با link...")
    print("   (صبر بین هر join)")

    joined = 0
    already = 0
    failed = 0
    fail_reasons = {}

    join_sem = asyncio.Semaphore(3)  # کم برای جلوگیری از flood

    async def do_join(phone):
        nonlocal joined, already, failed
        async with join_sem:
            _, result = await join_one(phone)
            if result == "JOINED":
                joined += 1
                print(f"  ✅ {phone}: JOINED")
            elif result == "ALREADY_MEMBER":
                already += 1
                print(f"  ℹ️ {phone}: قبلاً عضو")
            else:
                failed += 1
                fail_reasons[result] = fail_reasons.get(result, 0) + 1
                print(f"  ❌ {phone}: {result}")
            await asyncio.sleep(3)  # صبر بین joinها

    await asyncio.gather(*[do_join(p) for p in non_members])

    print(f"\n{'═'*50}")
    print(f"  ✅ joined: {joined}")
    print(f"  ℹ️ already: {already}")
    print(f"  ❌ failed: {failed}")
    print("\n  دلایل fail:")
    for reason, count in sorted(fail_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
