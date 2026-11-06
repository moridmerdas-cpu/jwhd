"""
عضویت همه اکانت‌های موجود در کانال هدف
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from models import database as db
from core.engine import make_client


async def join_one(phone):
    try:
        ss = db.get_session(phone)
        if not ss:
            return phone, "no_session"
        client = make_client(ss, phone=phone)
        await asyncio.wait_for(client.connect(), timeout=30)
        target = Config.TARGET_CHANNEL_USERNAME or Config.TARGET_CHANNEL_ID
        entity = await asyncio.wait_for(client.get_entity(target), timeout=15)
        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            await asyncio.wait_for(client(JoinChannelRequest(entity)), timeout=15)
            await client.disconnect()
            return phone, "joined"
        except Exception as e:
            err = str(e).lower()
            await client.disconnect()
            if "already" in err or "participant" in err:
                return phone, "already"
            return phone, f"err:{type(e).__name__}"
    except Exception as e:
        return phone, f"exc:{type(e).__name__}"


async def main():
    db.init_db()
    accounts = db.get_all_accounts()
    print(f"👥 {len(accounts)} اکانت")

    sem = asyncio.Semaphore(5)

    async def worker(phone):
        async with sem:
            return await join_one(phone)

    tasks = [worker(a["phone"]) for a in accounts]
    results = await asyncio.gather(*tasks)

    joined = sum(1 for _, r in results if r == "joined")
    already = sum(1 for _, r in results if r == "already")
    errors = [(p, r) for p, r in results if not r.startswith(("joined", "already"))]

    print(f"\n✅ join جدید: {joined}")
    print(f"⏭️  از قبل عضو: {already}")
    print(f"❌ خطا: {len(errors)}")
    for phone, err in errors:
        print(f"   {phone}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
