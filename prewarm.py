"""پیش‌گرم کردن entity cache برای همه اکانت‌ها"""
import asyncio, sys
sys.path.insert(0, '/root/tg_master_bot')
from config import Config
from models import database as db
from core.engine import make_client
from core.listener import _ENTITY_CACHE


async def prewarm(phone, target):
    try:
        c = make_client(db.get_session(phone), phone=phone)
        await asyncio.wait_for(c.connect(), timeout=20)
        if not await c.is_user_authorized():
            await c.disconnect()
            return phone, "NOT_AUTH"
        try:
            ent = await asyncio.wait_for(c.get_entity(target), timeout=15)
            _ENTITY_CACHE[(phone, str(target))] = ent
            await c.disconnect()
            return phone, "OK"
        except Exception as e:
            # تلاش دوم با input_entity
            try:
                ent = await asyncio.wait_for(c.get_input_entity(target), timeout=10)
                _ENTITY_CACHE[(phone, str(target))] = ent
                await c.disconnect()
                return phone, "OK_INPUT"
            except Exception:
                await c.disconnect()
                return phone, f"FAIL:{type(e).__name__}"
    except Exception as e:
        return phone, f"ERR:{type(e).__name__}"


async def main():
    db.init_db()
    accounts = db.get_all_accounts()
    target = Config.TARGET_CHANNEL_ID or Config.TARGET_CHANNEL_USERNAME
    print(f"📢 Target: {target}")
    print(f"👥 {len(accounts)} اکانت")
    print("⏳ Pre-warming entity cache...")

    sem = asyncio.Semaphore(20)
    results = {}

    async def one(acc):
        async with sem:
            p, r = await prewarm(acc["phone"], target)
            results[p] = r
            if r in ("OK", "OK_INPUT"):
                print(f"  ✅ {p}")
            else:
                print(f"  ❌ {p}: {r}")

    await asyncio.gather(*[one(a) for a in accounts], return_exceptions=True)

    from collections import Counter
    c = Counter(results.values())
    print(f"\n{'═'*50}")
    for r, n in c.most_common():
        print(f"  {r}: {n}")


if __name__ == "__main__":
    asyncio.run(main())
